"""Tests supabase/setup.sql on a local PostgreSQL (16 here) with Supabase-like roles: anon, authenticated, service_role (BYPASSRLS),
authenticator, and an admin that is not a superuser (like Supabase's "postgres"), with the old "auto-expose" default privileges
switched on (the worst case: every new table granted to the Data API roles). It needs psql and a server where the user "postgres" may
create databases and roles (trust or a password in PGPASSWORD); it makes and drops the databases mbapp and mbapp_old.

  python3 supabase/test_setup.py <host or socket folder> <port>        (selftest.py runs it when MEMEBOT_PG=<host>:<port> is set)

What it proves: anon reads live and app_config, saves and removes a subscription only through save_push_sub / drop_push_sub, and
can neither read push_subs or app_secret nor write live or app_config; the 25-row cap pushes out the row seen longest ago (never the
phone, which saves itself at every start), and rows no notification has reached before any that one has (so a stranger's made-up rows
never push out a phone that got a notification); at most 6 new subscriptions an hour are taken, also from 40 calls at the same moment
on 40 connections; keys of the wrong form are refused; service_role does what the bot does (marks delivered and counts failures); the
script runs twice without an error and keeps the data; a project set up with the first version of the script (one-argument
save_push_sub, direct inserts) is upgraded in place."""
import json, os, subprocess, sys

SOCK, PORT = sys.argv[1], sys.argv[2]
SETUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup.sql")
fails = []
# the push_subs part of the first version of the script (research, 2026-10-10): what an upgraded project starts from
OLD_SQL = r"""
grant usage on schema public to anon, authenticated, service_role;
create table if not exists public.push_subs (
  endpoint text primary key, sub jsonb not null, created timestamptz not null default now(),
  constraint push_subs_endpoint_ok check (length(endpoint) <= 1024
    and endpoint ~ '^https://(web\.push\.apple\.com|fcm\.googleapis\.com|updates\.push\.services\.mozilla\.com|[a-z0-9.-]+\.notify\.windows\.com)/'),
  constraint push_subs_sub_ok check (jsonb_typeof(sub) = 'object' and sub->>'endpoint' = endpoint and jsonb_typeof(sub->'keys') = 'object'
    and length(sub->'keys'->>'p256dh') between 80 and 100 and length(sub->'keys'->>'auth') between 16 and 32 and length(sub::text) <= 4096));
alter table public.push_subs enable row level security;
revoke all on table public.push_subs from anon, authenticated;
grant insert (endpoint, sub) on table public.push_subs to anon;
grant select, insert, update, delete on table public.push_subs to service_role;
drop policy if exists "push_subs: anon insert" on public.push_subs;
create policy "push_subs: anon insert" on public.push_subs for insert to anon with check (true);
create or replace function public.save_push_sub(p_sub jsonb) returns void language plpgsql security definer set search_path = '' as $$
declare ep text := p_sub->>'endpoint';
begin
  update public.push_subs set sub = p_sub where endpoint = ep;
  if not found then insert into public.push_subs (endpoint, sub) values (ep, p_sub); end if;
end; $$;
revoke all on function public.save_push_sub(jsonb) from public;
grant execute on function public.save_push_sub(jsonb) to anon, authenticated, service_role;
"""


def psql(sql, db, user="postgres", role=None, file=None):
    pre = ("set role %s;\n" % role) if role else ""
    args = ["psql", "-h", SOCK, "-p", PORT, "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A"]
    if file:
        args += ["-f", file]
        return subprocess.run(args, capture_output=True, text=True)
    return subprocess.run(args, input=pre + sql, capture_output=True, text=True)


def check(ok, what, extra=""):
    print(("  PASS " if ok else "  FAIL ") + what + (("  [" + extra.strip()[:300] + "]") if (extra and not ok) else ""))
    if not ok:
        fails.append(what)


def fresh(db):
    psql("drop database if exists %s;" % db, "postgres")
    r = psql("create database %s;" % db, "postgres")
    assert r.returncode == 0, r.stderr
    boot = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin noinherit; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin noinherit; end if;
  if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role nologin noinherit bypassrls; end if;
  if not exists (select 1 from pg_roles where rolname='authenticator') then create role authenticator login noinherit; end if;
  if not exists (select 1 from pg_roles where rolname='sbadmin') then create role sbadmin login createrole bypassrls; end if;
end $$;
grant anon, authenticated, service_role to authenticator;
grant anon, authenticated, service_role to sbadmin;
grant create, usage on schema public to sbadmin;
alter default privileges for role sbadmin in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges for role sbadmin in schema public grant all on functions to anon, authenticated, service_role;
alter default privileges for role sbadmin in schema public grant all on sequences to anon, authenticated, service_role;
"""
    r = psql(boot, db)
    assert r.returncode == 0, r.stderr


def sub(i, host="web.push.apple.com"):
    ep = "https://%s/QW%04dabcdefghijklmnopqrstuvwxyz0123456789" % (host, i)
    return {"endpoint": ep, "expirationTime": None, "keys": {"p256dh": "B" + "x" * 86, "auth": "a" * 22}}


def lit(o):
    return "'" + json.dumps(o).replace("'", "''") + "'::jsonb"


def main():
    db = "mbapp"
    fresh(db)
    for n in (1, 2):
        r = psql("", db, user="sbadmin", file=SETUP)
        check(r.returncode == 0 and "ERROR" not in r.stderr, "setup.sql runs as a non-superuser admin (run %d)" % n, r.stderr)

    ok = lambda sql, role: psql(sql, db, role=role)
    r = ok("select count(*) from public.live;", "anon")
    check(r.returncode == 0 and r.stdout.strip() == "2", "anon reads live (2 seeded rows)", r.stderr + r.stdout)
    for verb, sql in (("insert", "insert into public.live (id, doc) values ('x', '{}');"), ("update", "update public.live set doc='{}' where id='status';"),
                      ("delete", "delete from public.live where id='status';"),
                      ("upsert", "insert into public.live (id, doc) values ('status', '{}') on conflict (id) do update set doc=excluded.doc;")):
        for role in ("anon", "authenticated"):
            r = ok(sql, role)
            check(r.returncode != 0 and "permission denied" in r.stderr, "%s cannot %s live" % (role, verb), r.stderr)
    r = ok("select value from public.app_config;", "anon")
    check(r.returncode == 0, "anon reads app_config", r.stderr)
    r = ok("insert into public.app_config values ('x', '1');", "anon")
    check(r.returncode != 0 and "permission denied" in r.stderr, "anon cannot write app_config", r.stderr)
    for role in ("anon", "authenticated"):
        r = ok("select * from public.app_secret;", role)
        check(r.returncode != 0 and "permission denied" in r.stderr, "%s cannot read app_secret" % role, r.stderr)
        r = ok("insert into public.app_secret values ('k', 'v');", role)
        check(r.returncode != 0 and "permission denied" in r.stderr, "%s cannot write app_secret" % role, r.stderr)
        r = ok("select * from public.push_subs;", role)
        check(r.returncode != 0 and "permission denied" in r.stderr, "%s cannot read push_subs" % role, r.stderr)
        r = ok("insert into public.push_subs (endpoint, sub) values (%s->>'endpoint', %s);" % (lit(sub(1)), lit(sub(1))), role)
        check(r.returncode != 0 and "permission denied" in r.stderr, "%s cannot insert into push_subs directly" % role, r.stderr)
        r = ok("delete from public.push_subs;", role)
        check(r.returncode != 0 and "permission denied" in r.stderr, "%s cannot delete from push_subs directly" % role, r.stderr)

    r = ok("select public.save_push_sub(%s);" % lit(sub(1)), "anon")
    check(r.returncode == 0, "anon saves a subscription through save_push_sub (no prefs: both on)", r.stderr)
    r = ok("select prefs from public.push_subs;", "service_role")
    check(r.returncode == 0 and json.loads(r.stdout.strip() or "{}") == {"young": True, "pick": True}, "a new subscription gets both settings on", r.stdout + r.stderr)
    r = ok("select public.save_push_sub(%s, %s);" % (lit(sub(1)), lit({"young": False, "pick": True})), "anon")
    r2 = ok("select count(*), min(prefs::text) from public.push_subs;", "service_role")
    check(r.returncode == 0 and r2.stdout.strip().startswith("1|") and '"young": false' in r2.stdout, "saving again updates the same row and its settings", r.stderr + r2.stdout)
    r = ok("select public.save_push_sub(%s, %s);" % (lit(sub(1)), lit({"young": "yes"})), "anon")
    r2 = ok("select prefs from public.push_subs;", "service_role")
    check(r.returncode == 0 and json.loads(r2.stdout.strip()) == {"young": True, "pick": True}, "settings that are not true/false read as on", r.stderr + r2.stdout)
    r = ok("select public.save_push_sub(%s, '[1]'::jsonb);" % lit(sub(1)), "anon")
    check(r.returncode != 0, "settings that are not an object are refused", r.stderr)
    r = ok("select public.save_push_sub(%s);" % lit(sub(2, host="evil.example.com")), "anon")
    check(r.returncode != 0 and "push_subs_endpoint_ok" in r.stderr, "a subscription for another host is refused", r.stderr)
    bad = sub(3); bad["keys"]["auth"] = "x"
    r = ok("select public.save_push_sub(%s);" % lit(bad), "anon")
    check(r.returncode != 0 and "push_subs_sub_ok" in r.stderr, "a malformed subscription is refused", r.stderr)
    fmt = []
    for p256, auth in (("B" + "x" * 89, "a" * 22), ("A" + "x" * 86, "a" * 22), ("B" + "x" * 85 + ".", "a" * 22), ("B" + "x" * 86, "a" * 21 + "."), ("B" + "x" * 86, "a" * 24)):
        bad = sub(9); bad["keys"] = {"p256dh": p256, "auth": auth}
        r = ok("select public.save_push_sub(%s);" % lit(bad), "anon")
        fmt.append(r.returncode != 0 and "push_subs_sub_ok" in r.stderr)
    check(fmt == [True] * 5, "keys of the wrong length or with other characters are refused (p256dh: B and 86 base64url characters, auth: 22) %s" % fmt)
    r = ok("select public.save_push_sub(%s);" % lit(sub(4)), "anon")
    check(r.returncode == 0, "a second subscription is stored", r.stderr)

    # the cap (25 rows) and the hourly limit (6 new rows): a stranger with the publishable key cannot push the phone out
    q = lambda s_: "'" + s_["endpoint"] + "'"
    ok("delete from public.push_subs;", "service_role")
    for i in range(100, 124):          # 24 dead rows, made and last seen weeks ago (sub(100) the oldest)
        ok("insert into public.push_subs (endpoint, sub, created, seen) values (%s, %s, now() - interval '40 days', now() - interval '30 days' + interval '%d hours');"
           % (q(sub(i)), lit(sub(i)), i - 100), "service_role")
    phone = sub(7)                     # the phone: made two days ago, saved again when the app opened just now
    ok("insert into public.push_subs (endpoint, sub, created, seen) values (%s, %s, now() - interval '2 days', now());" % (q(phone), lit(phone)), "service_role")
    who = lambda: ok("select count(*), bool_or(endpoint = %s), bool_or(endpoint = %s), bool_or(endpoint = %s), bool_or(endpoint = %s) from public.push_subs;"
                     % (q(phone), q(sub(200)), q(sub(100)), q(sub(101))), "service_role").stdout.strip()
    r = ok("select public.save_push_sub(%s);" % lit(sub(200)), "anon")
    w = who()
    check(r.returncode == 0 and w == "25|t|t|f|t", "the table stops at 25 rows: a new subscription pushes out the one seen longest ago, the phone stays (%s)" % w, r.stderr)
    res = [ok("select public.save_push_sub(%s);" % lit(sub(i)), "anon") for i in range(201, 240)]
    stored = sum(1 for r in res if r.returncode == 0)
    refused = [r for r in res if r.returncode != 0]
    r = ok("select public.save_push_sub(%s, %s);" % (lit(phone), lit({"young": True, "pick": False})), "anon")
    r2 = ok("select prefs->>'pick' from public.push_subs where endpoint = %s;" % q(phone), "service_role")
    w = who()
    check(stored == 5 and refused and all("too many new subscriptions this hour" in x.stderr for x in refused) and r.returncode == 0 and r2.stdout.strip() == "false"
          and w.startswith("25|t|t|"),
          "at most 6 new subscriptions an hour: a flood of 40 stores 6, the phone stays and can still save itself (%d stored, %s)" % (stored + 1, w), r.stderr)
    # 40 calls at the same moment, each on its own connection and in its own transaction (as PostgREST runs them): still at most 6 new
    ok("delete from public.push_subs; insert into public.push_subs (endpoint, sub, created, seen) values (%s, %s, now() - interval '2 days', now() - interval '10 minutes');"
       % (q(phone), lit(phone)), "service_role")
    at = ok("select (clock_timestamp() + interval '2 seconds')::text;", "service_role").stdout.strip()
    procs = []
    for i in range(300, 340):
        a = ["psql", "-h", SOCK, "-p", PORT, "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A"]
        procs.append(subprocess.Popen(a, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        procs[-1].stdin.write("set role anon;\nselect pg_sleep_until('%s');\nselect public.save_push_sub(%s);\n" % (at, lit(sub(i))))
        procs[-1].stdin.close()
    errs = [p_.stderr.read() if p_.wait() != 0 else "" for p_ in procs]
    n_ok = sum(1 for e in errs if not e)
    w = ok("select count(*), count(*) filter (where created > now() - interval '1 hour'), bool_or(endpoint = %s) from public.push_subs;" % q(phone), "service_role").stdout.strip()
    check(n_ok == 6 and w == "7|6|t" and all("too many new subscriptions this hour" in e for e in errs if e),
          "40 calls at the same moment on 40 connections (as anon): 6 are stored, 34 refused, the phone stays (%d stored; rows, new, phone: %s)" % (n_ok, w))
    # a persistent stranger: 24 made-up rows saved over the last hours and kept fresh, the phone not opened for three days but reached by a notification
    ok("delete from public.push_subs;", "service_role")
    for i in range(400, 424):
        ok("insert into public.push_subs (endpoint, sub, created, seen) values (%s, %s, now() - interval '5 hours', now() - interval '%d minutes');" % (q(sub(i)), lit(sub(i)), i - 400), "service_role")
    ok("insert into public.push_subs (endpoint, sub, created, seen) values (%s, %s, now() - interval '9 days', now() - interval '3 days');" % (q(phone), lit(phone)), "service_role")
    r_d = ok("update public.push_subs set delivered = now() - interval '1 day', fails = 0 where endpoint = %s;" % q(phone), "service_role")
    r_a = ok("update public.push_subs set delivered = now() where endpoint = %s;" % q(sub(400)), "anon")
    r_n = ok("select public.save_push_sub(%s);" % lit(sub(450)), "anon")
    w = ok("select count(*), bool_or(endpoint = %s), bool_or(endpoint = %s), bool_or(endpoint = %s) from public.push_subs;" % (q(phone), q(sub(450)), q(sub(423))), "service_role").stdout.strip()
    check(r_d.returncode == 0 and r_a.returncode != 0 and "permission denied" in r_a.stderr and r_n.returncode == 0 and w == "25|t|t|f",
          "rows no notification reached go first: a stranger's 25th row pushes out the oldest made-up row, never the phone a notification reached, even unopened"
          " for three days; only the secret key marks a row delivered (%s)" % w)
    ok("update public.push_subs set fails = fails + 1 where endpoint = %s;" % q(phone), "service_role")
    r_f = ok("select fails, delivered is not null from public.push_subs where endpoint = %s;" % q(phone), "service_role")
    check(r_f.stdout.strip() == "1|t", "service_role counts a subscription's failures (the scan deletes it after 3 in a row at its own push host)", r_f.stderr + r_f.stdout)
    ok("delete from public.push_subs; insert into public.push_subs (endpoint, sub) values (%s, %s), (%s, %s);" % (q(sub(200)), lit(sub(200)), q(sub(5)), lit(sub(5))), "service_role")
    r = ok("select public.drop_push_sub(%s);" % lit(sub(200)), "anon")
    r2 = ok("select count(*) from public.push_subs where endpoint = %s;" % q(sub(200)), "service_role")
    check(r.returncode == 0 and r2.stdout.strip() == "0", "anon removes a subscription through drop_push_sub", r.stderr + r2.stdout)
    r = ok("select public.live_touch();", "anon")
    check(r.returncode != 0, "anon cannot call the trigger functions", r.stderr)

    # service_role (the secret key): what the bot does
    r = ok("insert into public.live (id, doc) values ('status', '{\"a\":1}') on conflict (id) do update set doc = excluded.doc returning ver;", "service_role")
    v1 = r.stdout.strip().splitlines()[0] if r.returncode == 0 else ""
    r = ok("insert into public.live (id, doc) values ('status', '{\"a\":2}') on conflict (id) do update set doc = excluded.doc returning ver;", "service_role")
    v2 = r.stdout.strip().splitlines()[0] if r.returncode == 0 else ""
    check(v1.isdigit() and v2.isdigit() and int(v2) > int(v1), "service_role upserts live and ver goes up (%s -> %s)" % (v1, v2), r.stderr)
    r = ok("insert into public.app_secret values ('vapid_private_key', 'k') on conflict (key) do nothing; select value from public.app_secret;", "service_role")
    check(r.returncode == 0 and r.stdout.strip() == "k", "service_role writes and reads app_secret", r.stderr)
    r = ok("insert into public.app_config values ('vapid_public_key', '\"B\"') on conflict (key) do update set value = excluded.value; select value from public.app_config;", "service_role")
    check(r.returncode == 0 and r.stdout.strip() == '"B"', "service_role writes app_config", r.stderr)
    r = ok("select endpoint, sub, prefs from public.push_subs limit 1; delete from public.push_subs where endpoint = %s;" % ("'" + sub(1)["endpoint"] + "'"), "service_role")
    check(r.returncode == 0, "service_role reads and deletes push_subs", r.stderr)
    r0 = ok("select count(*) from public.push_subs;", "service_role")
    r2 = psql("", db, user="sbadmin", file=SETUP)
    r3 = ok("select count(*) from public.push_subs;", "service_role")
    r4 = ok("select doc::text from public.live where id='status';", "anon")
    check(r2.returncode == 0 and r3.stdout.strip() == r0.stdout.strip() != "0" and '"a": 2' in r4.stdout, "running setup.sql again keeps the data", "rc=%s count=%s doc=%s" % (r2.returncode, r3.stdout.strip(), r4.stdout.strip()))
    r = ok("select count(*) from pg_proc where proname = 'save_push_sub';", "sbadmin")
    check(r.stdout.strip() == "1", "one save_push_sub only (PostgREST refuses overloaded calls)", r.stdout)

    if True:         # a project set up with the first version of the script is upgraded in place
        db2 = "mbapp_old"
        fresh(db2)
        r = psql(OLD_SQL, db2, user="sbadmin")
        r1 = psql("set role anon; insert into public.push_subs (endpoint, sub) values (%s->>'endpoint', %s);" % (lit(sub(1)), lit(sub(1))), db2)
        junk = sub(8); junk["keys"]["p256dh"] = "B" + "x" * 80 + "!!!!!!"      # passed the first script's length check
        r1b = psql("set role anon; insert into public.push_subs (endpoint, sub) values (%s->>'endpoint', %s);" % (lit(junk), lit(junk)), db2)
        r2 = psql("", db2, user="sbadmin", file=SETUP)
        r2b = psql("set role service_role; select count(*) from public.push_subs where endpoint = '%s';" % junk["endpoint"], db2)
        r3 = psql("set role service_role; select prefs::text, seen is not null from public.push_subs;", db2)
        r4 = psql("set role anon; insert into public.push_subs (endpoint, sub) values (%s->>'endpoint', %s);" % (lit(sub(2)), lit(sub(2))), db2)
        r5 = psql("select count(*) from pg_proc where proname = 'save_push_sub'; set role anon; select public.save_push_sub(%s);" % lit(sub(3)), db2)
        check(r.returncode == 0 and r1.returncode == 0 and r1b.returncode == 0 and r2.returncode == 0 and '"young": true' in r3.stdout and r4.returncode != 0
              and r5.returncode == 0 and r5.stdout.strip().splitlines()[0] == "1" and r2b.stdout.strip() == "0",
              "a project set up with the first script is upgraded: old rows get settings, a junk row that fails the new key checks is removed, direct insert is gone, one save_push_sub",
              r.stderr + r1.stderr + r1b.stderr + r2.stderr + r2b.stdout + r3.stdout + r4.stderr + r5.stderr + r5.stdout)
        psql("drop database if exists %s;" % db2, "postgres")
    psql("drop database if exists %s;" % db, "postgres")
    print("\n%d SQL checks failed" % len(fails) if fails else "\nSQL ALL PASS")
    sys.exit(1 if fails else 0)


main()
