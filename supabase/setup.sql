-- =====================================================================
-- Meme-Bot iPhone app: one-time setup of the free Supabase project (2026)
-- Paste into Dashboard > SQL Editor > New query > Run.
-- Safe to run again (idempotent). Grants are explicit on purpose: new
-- projects no longer give the Data API roles access to new tables.
-- Fake money only: these tables hold the scan's live view and the
-- phone's notification subscription, nothing else.
--
--   live        rows 'status' (small, every few seconds) and 'current'
--               (the whole live record); anyone may read, only the
--               secret key (service_role) may write
--   push_subs   the phone's push subscriptions with their settings;
--               the page saves them through save_push_sub and removes
--               them through drop_push_sub, it can never read them;
--               at most 25 rows and 6 new ones an hour (the publishable
--               key is public), the phone's own row always stays
--   app_config  public settings (the VAPID public key); anyone may read
--   app_secret  the VAPID private key; the secret key only
-- =====================================================================

-- The Data API roles must see the schema (already true on Supabase; harmless).
grant usage on schema public to anon, authenticated, service_role;

-- ---------------------------------------------------------------------
-- 1) live: anyone may READ; only the secret key (service_role) may WRITE
-- ---------------------------------------------------------------------
create table if not exists public.live (
  id      text        primary key,
  updated timestamptz not null default now(),
  ver     bigint      not null default 0,
  doc     jsonb       not null default '{}'::jsonb
);

-- Every write bumps ver and updated on the server, so the bot only sends {id, doc}.
-- ver = epoch milliseconds, strictly increasing per row.
create or replace function public.live_touch()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  now_ms bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint;
begin
  new.updated := now();
  if tg_op = 'UPDATE' then
    new.ver := greatest(old.ver + 1, now_ms);
  else
    new.ver := now_ms;
  end if;
  return new;
end;
$$;
revoke all on function public.live_touch() from public, anon, authenticated;

drop trigger if exists live_touch on public.live;
create trigger live_touch
  before insert or update on public.live
  for each row execute function public.live_touch();

alter table public.live enable row level security;
revoke all on table public.live from anon, authenticated;
grant select on table public.live to anon, authenticated;
grant select, insert, update, delete on table public.live to service_role;

drop policy if exists "live: public read" on public.live;
create policy "live: public read"
  on public.live for select
  to anon, authenticated
  using (true);

insert into public.live (id, doc) values ('status', '{}'), ('current', '{}')
on conflict (id) do nothing;

-- ---------------------------------------------------------------------
-- 2) push_subs: no direct access for the page; two functions below
-- ---------------------------------------------------------------------
create table if not exists public.push_subs (
  endpoint text        primary key,
  sub      jsonb       not null,
  created  timestamptz not null default now()
);
-- added after the first version of this script: settings and last-seen time
alter table public.push_subs add column if not exists prefs jsonb not null default '{"young": true, "pick": true}'::jsonb;
alter table public.push_subs add column if not exists seen timestamptz not null default now();

-- only real push services (Apple for the iPhone; the others for desktop tests)
alter table public.push_subs drop constraint if exists push_subs_endpoint_ok;
alter table public.push_subs add constraint push_subs_endpoint_ok check (
  length(endpoint) <= 1024
  and endpoint ~ '^https://(web\.push\.apple\.com|fcm\.googleapis\.com|updates\.push\.services\.mozilla\.com|[a-z0-9.-]+\.notify\.windows\.com)/'
);
-- the shape of PushSubscription.toJSON()
alter table public.push_subs drop constraint if exists push_subs_sub_ok;
-- rows saved before these checks existed that fail them are junk: removed first, so adding the checks never fails
delete from public.push_subs
 where not (coalesce(sub->'keys'->>'p256dh', '') ~ '^B[A-Za-z0-9_-]{86}=?$'
            and coalesce(sub->'keys'->>'auth', '') ~ '^[A-Za-z0-9_-]{22}(==)?$');
alter table public.push_subs add constraint push_subs_sub_ok check (
  jsonb_typeof(sub) = 'object'
  and sub->>'endpoint' = endpoint
  and jsonb_typeof(sub->'keys') = 'object'
  and sub->'keys'->>'p256dh' ~ '^B[A-Za-z0-9_-]{86}=?$'    -- a P-256 public key: 65 bytes in base64url, starting 0x04
  and sub->'keys'->>'auth' ~ '^[A-Za-z0-9_-]{22}(==)?$'      -- 16 bytes in base64url
  and length(sub::text) <= 4096
);
-- settings: {"young": true|false, "pick": true|false}
alter table public.push_subs drop constraint if exists push_subs_prefs_ok;
alter table public.push_subs add constraint push_subs_prefs_ok check (
  jsonb_typeof(prefs) = 'object'
  and jsonb_typeof(prefs->'young') = 'boolean'
  and jsonb_typeof(prefs->'pick') = 'boolean'
  and length(prefs::text) <= 200
);

-- Size cap: the publishable key is public, so the table never grows past 25 rows.
-- A new subscription keeps the 24 seen most recently and pushes out the rest:
-- the one seen longest ago goes (a dead one, usually: the app saves its own
-- subscription again every time it opens, so the phone is always among the newest).
create or replace function public.push_subs_cap()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  delete from public.push_subs
   where endpoint in (select endpoint from public.push_subs
                       order by seen desc, created desc
                       offset 24);
  return new;
end;
$$;
revoke all on function public.push_subs_cap() from public, anon, authenticated;

drop trigger if exists push_subs_cap on public.push_subs;
create trigger push_subs_cap
  before insert on public.push_subs
  for each row execute function public.push_subs_cap();

alter table public.push_subs enable row level security;
revoke all on table public.push_subs from anon, authenticated;
grant select, insert, update, delete on table public.push_subs to service_role;
drop policy if exists "push_subs: anon insert" on public.push_subs;   -- the first version let the page insert directly
-- No policy and no grant for anon / authenticated = no SELECT, INSERT, UPDATE or DELETE.

-- Save (insert or update) one subscription and its settings:
-- POST /rest/v1/rpc/save_push_sub {"p_sub": <subscription.toJSON()>, "p_prefs": {"young": true, "pick": false}}
drop function if exists public.save_push_sub(jsonb);                    -- the first version had one argument
create or replace function public.save_push_sub(p_sub jsonb, p_prefs jsonb default null)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  ep text := p_sub->>'endpoint';
  pr jsonb := null;
begin
  if p_prefs is not null then
    if jsonb_typeof(p_prefs) <> 'object' then
      raise exception 'p_prefs must be an object';
    end if;
    pr := jsonb_build_object(
      'young', case when jsonb_typeof(p_prefs->'young') = 'boolean' then (p_prefs->'young')::boolean else true end,
      'pick',  case when jsonb_typeof(p_prefs->'pick')  = 'boolean' then (p_prefs->'pick')::boolean  else true end);
  end if;
  update public.push_subs
     set sub = p_sub, seen = now(), prefs = coalesce(pr, prefs)
   where endpoint = ep;
  if not found then
    -- at most 6 NEW subscriptions an hour (saving one that is already there always works):
    -- a stranger with the publishable key cannot flood the table and push the phone out
    if (select count(*) from public.push_subs where created > now() - interval '1 hour') >= 6 then
      raise exception 'too many new subscriptions this hour, try again later';
    end if;
    insert into public.push_subs (endpoint, sub, prefs)
    values (ep, p_sub, coalesce(pr, '{"young": true, "pick": true}'::jsonb));
  end if;
end;
$$;
revoke all on function public.save_push_sub(jsonb, jsonb) from public;
grant execute on function public.save_push_sub(jsonb, jsonb) to anon, authenticated, service_role;

-- Remove one subscription (notifications turned off in the app):
-- POST /rest/v1/rpc/drop_push_sub {"p_sub": <subscription.toJSON()>}
create or replace function public.drop_push_sub(p_sub jsonb)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  delete from public.push_subs where endpoint = p_sub->>'endpoint';
end;
$$;
revoke all on function public.drop_push_sub(jsonb) from public;
grant execute on function public.drop_push_sub(jsonb) to anon, authenticated, service_role;

-- ---------------------------------------------------------------------
-- 3) app_config: public read (the VAPID public key); writes with the secret key
-- ---------------------------------------------------------------------
create table if not exists public.app_config (
  key   text  primary key,
  value jsonb not null
);
alter table public.app_config enable row level security;
revoke all on table public.app_config from anon, authenticated;
grant select on table public.app_config to anon, authenticated;
grant select, insert, update, delete on table public.app_config to service_role;

drop policy if exists "app_config: public read" on public.app_config;
create policy "app_config: public read"
  on public.app_config for select
  to anon, authenticated
  using (true);

-- ---------------------------------------------------------------------
-- 4) app_secret: NO access for anon / authenticated at all (secret key only)
-- ---------------------------------------------------------------------
create table if not exists public.app_secret (
  key   text primary key,
  value text not null
);
alter table public.app_secret enable row level security;   -- and deliberately no policies
revoke all on table public.app_secret from anon, authenticated;
grant select, insert, update, delete on table public.app_secret to service_role;

-- ---------------------------------------------------------------------
-- 5) Make the Data API see the new tables and functions right away
-- ---------------------------------------------------------------------
notify pgrst, 'reload schema';

-- ---------------------------------------------------------------------
-- Optional check (run separately): who can do what
-- select table_name, grantee, string_agg(privilege_type, ', ' order by privilege_type) as privs
-- from information_schema.role_table_grants
-- where table_schema = 'public'
--   and table_name in ('live','push_subs','app_config','app_secret')
--   and grantee in ('anon','authenticated','service_role')
-- group by 1, 2 order by 1, 2;
-- ---------------------------------------------------------------------
