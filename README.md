# Long-history rows for the Meme-Bot, part 2 (fake money only)

Data provided by [Slink21]. Pumpfun Solana Dataset (2026). https://huggingface.co/datasets/Slinky21/Pumpfun_v2_dataset (CC BY 4.0)

Derived (changed) from that data set by research/history_build2.py: every PumpSwap swap of the coins that graduated from pump.fun between 10 August and 8 October 2026, made into one-minute bars (bars/, by graduation day) and into rows at whole hours after each graduation (hourly/, by day) with screener-like numbers, the price 1.7 hours later and the path over 6 hours. Market cap, liquidity and the rug time are computed, not recorded; see the script's header. Rows whose windows touch a recorder outage are flagged (gap_pre, gap_1, gap_6).
