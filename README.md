# Portfolio

A private mutual-fund dashboard with Excel imports, daily AMFI NAV history, NSE total-return benchmarks, ownership-aware XIRR, purchase lots, financial-year reports and a detailed audit view.

## Run

For a fresh checkout, create the local fund-mapping file (leave an existing file intact):

```sh
test -f config/schemes.json || cp config/schemes.example.json config/schemes.json
```

Start Docker Desktop, then run from this folder:

```sh
docker compose up
```

Open **http://localhost:8000**. The first build downloads dependencies. The first refresh downloads historical prices and can take several minutes. Subsequent refreshes reuse the persistent cache. Use **Refresh data** to import new Excel files and backfill missing dates. The app also refreshes at **7 AM Asia/Kolkata** while running and catches up when restarted.

```sh
docker compose up -d           # run in the background
docker compose stop            # stop, retaining all cached data
docker compose up --build -d   # rebuild after changing source code
docker compose logs -f        # inspect service logs
```

The service is exposed only on this machine's loopback interface. No portfolio data is uploaded to any external service. Public data requests contain fund identifiers / index names and date ranges only. Charts and scripts are bundled and work offline with cached data.

## Excel inputs

Keep yearly `.xlsx` exports in this folder or in subfolders, for example:

```text
Person_A/Mutual_Funds_Order_History_....xlsx
Person_A/cas_detailed_report_....xlsx
Person_B/Mutual_Funds_Order_History_....xlsx
Person_B/cas_detailed_report_....xlsx
```

PAN and name are read from each workbook. Expected table columns: **Scheme Name, Transaction Type, Units, NAV, Amount, Date**. Source files are mounted read-only and are never changed. Capital-gains reports are not accepted as transaction history. An invalid workbook leaves the previous imported ledger intact and reports the error.

Detailed CAS workbooks with **Transaction Description** instead of Transaction Type are supporting evidence, not a second transaction ledger. This avoids double-counting their overlapping higher-precision purchases, cancelled orders and folio consolidation rows. Explicit outgoing **Gifting of units** entries can reconcile a unique annual redemption and matching incoming purchase on the same date, fund, units, NAV and amount. A matching explicit incoming gift in the recipient's CAS can establish the recipient even before their annual export catches up. The linked cash rows remain visible in Data details but are replaced by one transfer in calculations. An annual incoming row arriving later is linked, without adding units again. Original acquisition dates and FIFO cost follow the units; individual XIRR uses the CAS transfer-date NAV. Gifts cancel when both matched owners are selected. An unmatched recipient is clearly flagged and treated as an outgoing ownership transfer until unique incoming evidence arrives. No recipient is guessed. Removing an automatically verified transfer restores its source cash rows and saves that override across refreshes.

Overlapping exports are deduplicated by PAN, scheme, date, type, units, NAV, amount and occurrence number. Two identical rows within one export remain separate until reviewed, because the exports have no order IDs. **Purchases and redemptions** with identical units, NAV and amount on the same date or within seven days are flagged across the complete history, with no 500-row cutoff. **Data details → Review issues** respects the selected people, fund and dates, and defaults to **Unresolved** with **Resolved** and **All** filters. Blocking unit shortages include the affected fund, date and available versus required units. Use **Keep this entry** to exclude the other copies, or **Keep all entries** to confirm genuine separate orders. Choices that introduce or worsen a unit shortage are rejected before saving. The dashboard warns about unresolved groups; their included entries still count in totals. Decisions persist across refreshes and overlapping exports. Source workbooks are never edited. Transactions belonging to different PANs are never deduplicated against one another.

CAS can resolve two special cases automatically. When it explicitly identifies a purchase consolidated from another folio, and Groww contains exactly two matching purchases and one redemption, the original acquisition is retained once; the matching folio-out and folio-in entries add no units or external cash flows. This preserves the original FIFO cost and date. When one CAS report explicitly lists each of several otherwise identical purchases, all verified orders are retained. Counts from overlapping CAS reports are never added together as proof of extra orders. These source-verified entries are marked **CAS verified** and cannot be removed through duplicate review. Conflicting older exclusions are repaired on import; unresolved cases still require review.

Folder names are for organization: PAN identifies each person. Renaming or moving a file does not reset transactions, exclusions or transfer links. Additional people can use their own named folders.

Units are never rounded by the dashboard. Matched CAS purchases and redemptions supply their more precise quantities without replacing the original transaction IDs, dates or recorded cash amounts. Matching requires the same owner, fund, date and direction, and compatible units, NAV and cash amount. Each individual report must establish the order count; conflicting quantities or ambiguous FIFO order assignments retain the original source values. **Data details → Transactions** shows the calculation units, original statement units and their source. CAS-verified gifts use the full CAS quantity. Unit additions, FIFO subtraction and lot allocations use decimal arithmetic; the UI and CSV exports retain quantity precision, and transfer inputs accept arbitrary decimal steps. INR displays use up to two decimals; stored prices and cash calculations keep their precision.

Older Groww exports already contain only two-decimal units. Missing digits cannot be reconstructed without precise source evidence. Small shortages within the disclosed source-rounding tolerance remain flagged; for verified gifts original cost is preserved and the recipient receives the full CAS quantity. A partial CAS never replaces the complete annual cash ledger or invents missing purchases.

**Your funds** defaults to **Active**. **Zero** includes exited funds and remaining holdings worth ₹5 or less, including rounding residuals. **All** shows both. This is a display filter: small balances remain in portfolio value, cost and XIRR, and missing prices are never treated as zero. Current holdings/CAS with precise units are recommended for final reconciliation.

Click a fund to open its **fund details page**: current value, original remaining cost, gain, XIRR, exact units, NAV, transfer values and growth against the four TRI benchmarks. Fund history includes transactions, original purchase lots, financial/calendar-year investments and transfers, with links to the detailed audit view. The header's people and period filters apply to personal investment returns. Fund URLs support reload and browser Back/Forward.

Use **Compare** or **Add / remove funds** to choose multiple funds and toggle indexes. In fund growth and comparison charts, click a legend label to show or hide that series; double-click to isolate it, and double-click again to restore all series. Hidden series are excluded from hover values. Legend visibility survives refreshes and value/return mode changes without changing the compared date range or recalculating investments. The index checkboxes choose which indexes are included in the comparison and its common date range. **Your investments** combines the selected funds and replays their actual dated cash flows in each index; the per-fund XIRR table independently replays each row's own cash flows. **Market performance** plots the gain/loss on an equal ₹10,000 investment in each fund and index, or their NAV/TRI Return %. Both views start at zero; the ending-value table still shows the full investment value. This price-based comparison is independent of ownership and cash-flow amounts. Its common range starts once all chosen instruments have prices and ends at the earliest last observation, limited to the selected period. Base and closing prices must be no more than seven days old; older interior observations leave gaps. Nonoverlapping or missing history is shown as unavailable. Adding a second fund opens this view automatically. Market returns and personal XIRR remain explicitly separate.

**Since inception**, **1Y**, **3Y**, **5Y** and **Custom dates** set the calculation window across the portfolio, fund details and comparisons. Custom dates take effect after **Apply dates**; reversed, invalid or future dates are rejected. A historical end date labels the value KPI **Value at period end**. Rolling calendar years clamp leap days to the last valid day in February.

Every growth curve begins at zero. **Growth ₹** is cumulative gain/loss after subtracting opening holdings and net period contributions, including boundary transfers and payouts; a deposit alone is not a gain. Existing holdings seed the window at the previous day's closing value, and indexes receive the same opening amount at their previous closing TRI. The zero opening is plotted separately from the first day's close so that day's actual gain is retained. **Return %** compares compounded time-weighted returns while invested. Missing opening valuations remain unavailable. Value and original-cost KPIs retain their actual amounts.

The growth chart supports drag-to-zoom, wheel/trackpad zoom, pan controls and **Reset zoom**. Its tooltip follows the pointer near the hovered date, stays readable while hovering, flips at chart edges and disappears when the pointer leaves the plotting area. No pin or close action is needed. Chart heights remain fixed during width changes and hidden-panel transitions. Zoom changes only the visible area, without recalculating the baseline, period returns or KPIs. Reset zoom (or double-click) restores the complete selected window. Zoom survives refreshes and resets when people, period or growth/return mode change. Open dashboards detect refreshed data and server restarts automatically.

## People and transfers

Select people independently in the header. Selecting multiple people calculates combined totals and recomputes XIRR from their combined cash flows.

1. Add the recipient through **Transfers → Add person**, or import their Excel history.
2. Record an actual unit transfer: effective date, sender, recipient, fund and units.
3. Choose exact original purchase lots where known; otherwise the form explicitly uses FIFO.
4. Supply transfer-date NAV or let the app use a published NAV no more than seven days old.

Original purchase costs and dates follow the transferred lots. For individual ownership returns, outgoing units create a positive synthetic cash flow and incoming units a negative one, both at transfer-date market value. These cash flows cancel when both people are selected. Transfers do not count as fresh yearly purchases. A later redemption uses the recipient's ownership basis for their realized return while retaining historical original cost separately.

Do not also import the same transfer as a cash purchase/redemption. Unsupported transfer rows are flagged for explicit reconciliation. Transfer entry does not execute any financial transaction.

## Calculations

- **Daily value:** ledger units × latest published NAV on/before the valuation day. Source quote dates are always retained. No interpolated observations are written. A 14-day history buffer covers prior business-day quotes. A launch-day execution preceding the first public NAV by up to seven days may use the statement execution NAV, explicitly labeled, without overwriting published quotes. TWR and drawdown remain unavailable if an active holding's NAV is older than seven days on a reference trading session. Weekends/closed reference sessions alone do not invalidate an otherwise priced history. Published Nifty 50 dates identify reference sessions; weekdays are the fallback outside loaded reference coverage.
- **Remaining invested cost:** FIFO historical purchase cost of units still held, including transferred original lots.
- **Average invested NAV:** remaining original cost / remaining units.
- **Ownership gain:** ending value + withdrawals + distributions + transfer-outs − purchases − transfer-ins − period opening value. Transfers use market value when crossing the selected ownership boundary.
- **Absolute return:** ownership gain / all negative ownership cash flows, including the opening value for a selected period. This denominator is separate from remaining original cost.
- **XIRR:** actual dated cash flows, ending market value as a final positive flow, 365-day annualization using `pyxirr`. Combined XIRR is not an average. For a selected shorter period, the previous day's closing value is the initial synthetic investment. A missing opening price makes that period's return unavailable, while current value still uses available end-date prices. IRRs for non-conventional cash flows can have multiple mathematical solutions; the library's default solution is used.
- **TWR:** daily end-of-day cash-flow convention, `(closing value + investor cash flow) / previous closing value`, compounded. Maximum drawdown is measured on this flow-adjusted series. The cash-flow timing convention is approximate when investments and withdrawals occur intraday.
- **Yearly reports:** calendar year or Indian financial year, April–March. Purchases, withdrawals, net contributions and transfer values are separate.
- **Benchmarks:** Nifty 50 TRI, Nifty LargeMidcap 250 TRI (the chosen interpretation of “Nifty 250”), Nifty 500 TRI, and Nifty Midcap 150 TRI. For an existing holding at the period start, each index is seeded with the same opening value at the latest TRI on/before the preceding day (no more than seven days old). Subsequent ownership cash flows execute on the next published index date within seven days. The benchmark ledger explicitly identifies the opening investment and its quote date. Dividends are included through TRI. If withdrawals would force negative benchmark holdings, that comparison is unavailable. Portfolio and benchmark comparisons identify their valuation dates.
- **Currency / tax:** INR, before personal taxes. Recorded transaction cash amounts are used; fees or payouts absent from the exports cannot be inferred. Fund expenses already reflected in NAV are not deducted again.

## Public data and refresh

AMFI: `https://portal.amfiindia.com/spages/NAVAll.txt` and its historical NAV download, in batches under the published 90-day limit. Fund-house batches reduce bandwidth. Scheme codes must match plan/option exactly. Ambiguous names require confirmation under **Data status**. Add verified mappings to `config/schemes.json` or use the UI. Changing a mapping invalidates its cached prices/history windows.

For old periods that AMFI redirects or does not return, the app uses the public MFAPI historical mirror. Scheme code, plan/option and ISIN are checked; the latest overlapping observations must agree with AMFI. Widespread historical disagreement is rejected. Isolated older differences retain the official AMFI value and are disclosed in provider notes. Mirror observations fill only missing dates and never replace official AMFI quotes. Their source is explicitly shown in Data details and provider notes. No holdings, amounts or PANs are sent.

Exited schemes absent from the current AMFI catalog can have explicit historical definitions in `config/schemes.json`. Their mirror identity must match that definition and dated statement NAVs must agree to the export's two-decimal precision. These observations are labeled as archived history without live AMFI overlap. A matured fund is not substituted with a successor fund's prices. Fund-house downloads stop at the latest published date, avoiding false weekend-only download errors. Multiple imported names sharing one AMFI code each receive that code's prices.

NSE: `https://www.niftyindices.com/Backpage/getTotalReturnIndexString`. The app retries failed requests, saves successful batches independently and retries failures on the next refresh. Recent dates are rechecked for corrections. Interior gaps are compared with published domestic reference dates and their containing windows are retried. Different fund holidays and special exchange sessions mean these are labeled potential gaps, not confirmed download failures. Data status shows one row per fund/index across all sources, with the exact flagged dates; Price gaps lists each date separately. These checks cover interior dates between the first and last stored observations, not a guarantee of complete history. Public endpoints can be unavailable or reject automated requests; failed downloads remain visible and a price index is never silently used in place of TRI.

If NSE's automatic endpoint is unavailable, download **Total Returns Index Values** from [NSE Indices historical data](https://www.niftyindices.com/reports/historical-data) and use **Data details → Index levels → Import TRI CSV**. CSVs must contain `Date` and `Total Returns Index` (or `TotalReturnsIndex` / `TRI`). A plain `Close` column is rejected. Imported observations retain their user-supplied provenance.

The data tab includes transactions, daily NAVs, index levels, daily selected-portfolio valuations, the simulated benchmark ledger, original purchase lots, XIRR cash flows and data coverage. Tables support filters, sorting, pagination and CSV export. Masked PANs are used in UI metadata. Full PANs exist only in the local input files and database.

## Persistence and backup

`portfolio-data` is a Docker named volume containing `/state/portfolio.sqlite`: downloaded prices, imported transactions, people, transfers, exclusions and refresh metadata. `docker compose stop` and ordinary restarts retain it. **Do not run `docker compose down -v` unless you intend to erase that data.** Back up the database (using SQLite's backup API for a live database), original Excel files and `config/` before migrating machines. Source workbooks and `config/` are mounted read-only.

## Sharing the source safely

Git includes project source, documentation, shared build configuration and an empty fund-mapping template. The local `tests/` folder, personal input folders, spreadsheets, CSV/PDF exports, local databases, environment files, credentials, logs and `config/schemes.json` are ignored. New root-level files and folders are ignored unless explicitly allowed in `.gitignore`. Your local data stays on your machine.

Before each push, review `git diff --cached` and `git ls-files` for accidentally added data. Ignore rules do not protect files added with `git add -f` or data pasted into source files, and cannot remove data from existing Git history.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
AUTO_REFRESH=0 .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Development uses `.local-state/`, independently of Docker's volume. FastAPI's API reference is available at `/api/docs`. Docker runs as a non-root user and has a health check.
