# OOP with Python: Assignment 2 (Advent 2026)

**Student:** _[MBUYA CHRISTINE FRIDAH, S26M19/029]_  **Programme:** _[MSDS]_

Two mini-projects:

| # | Notebook | Code | What it does |
|---|---|---|---|
| 1 | `project1_weather.ipynb` | `src/weather/` | Turns a place name into a weather forecast using the Open-Meteo and MET Norway web APIs, with retries, clear errors and a written report |
| 2 | `project2_tax_engine.ipynb` | `src/tax/` | An extensible Uganda tax engine: PAYE (resident and non-resident), NSSF, Local Service Tax, VAT, corporate income tax, and a salary-versus-dividend tax planner |

## Repository layout

```
├── README.md
├── requirements.txt
├── project1_weather.ipynb
├── project2_tax_engine.ipynb
├── src/
│   ├── weather/   http.py (retry wrapper, exceptions)  api.py (the API calls)
│   │              parsing.py (JSON -> DataFrame)       display.py (table, chart, diagram)
│   └── tax/       money.py  errors.py  core.py (Tax, TaxContext, TaxResult)  schedules.py
│                  employment.py (PAYE, NSSF, LST, payroll)  business.py (VAT, corporate, withholding)
│                  planner.py (Extension B)
├── tests/         pytest tests (109), all runnable offline
├── samples/       saved sample JSON for the offline weather checks (see samples/README.md)
└── figures/       PNG copies of the charts, written by the notebooks
```

## Setup

Requires Python 3.9 or newer.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```bash
pytest -q                            # 109 tests, no internet needed
jupyter notebook                     # open a notebook -> Kernel -> Restart & Run All
```

Run the notebooks from the repository root, because they import from `src/`.

### Project 1 needs two things

1. **An internet connection**, to reach `geocoding-api.open-meteo.com`, `api.open-meteo.com` and `api.met.no`.
2. **Your own contact email**, which is sent in the `User-Agent` header as the API operators request. Either set an environment variable before starting Jupyter:

   ```bash
   export WEATHER_CONTACT_EMAIL="your.name@your-university.ac.ug"      # Windows PowerShell: $env:WEATHER_CONTACT_EMAIL="..."
   ```

   or replace the placeholder in the notebook's configuration cell. No contact details are stored in the code.

The configuration cell (location, number of days, email) is the only manual input. If a request fails and `USE_SAMPLES_IF_OFFLINE = True`, the notebook says so in capitals and continues with the saved sample JSON, so *Restart & Run All* always completes. Set it to `False` to make failures stop the run. Each run prints a "Data mode per step" table showing which steps used live data.

Project 2 needs no internet.

## Summary of findings

**Project 1: weather.** The same geocoding call takes about eight lines with `urllib` and three with `requests`, and `requests` gives one family of exceptions instead of several. All requests go through one wrapper that sets a timeout, calls `raise_for_status()`, retries temporary failures (connection errors, timeouts, HTTP 5xx/429) with exponential backoff up to a cap, never retries 4xx errors, and raises `WeatherAPIError` on final failure. Zero results (the API omits the `results` key), ambiguous names, invalid coordinates, a simulated network outage and a 1 ms timeout are all handled with specific messages. MET Norway is added as a second source and reshaped to the same daily columns for comparison. _[After running live, add one sentence here on what your forecast and the two-source comparison showed.]_

**Project 2: tax engine.** PAYE is driven by dated rate schedules, so the engine applies the pre-July-2026 bands or the Income Tax (Amendment) Act, 2026 bands depending on the pay date, and raises `NoScheduleForDateError` for dates it has no schedule for. Under the 2026 schedule a resident on UGX 3,000,000 a month pays PAYE of 788,250 (802,000 before), and every resident above 485,000 saves 13,750 a month. Deductions run in the order LST → PAYE → NSSF, because LST is deductible before PAYE and NSSF is not. Zero-rated and exempt supplies look alike to a customer but differ sharply for the seller: on identical purchases an exporter is refunded input VAT while an exempt supplier is not. The tax planner shows that for an owner-manager, salary is taxed less than dividends at every profit level tested (dividends bear a flat 40.5 %), although dividends leave more cash in hand above roughly UGX 140 million of annual profit because salary diverts 15 % into NSSF.

## Tax rates and sources (version used: checked 7 October 2026)

| Tax | Rule | Source |
|---|---|---|
| PAYE, resident, from 1 Jul 2026 | Nil to 335,000; 20 % to 410,000; 25 % to 485,000; 30 % above; +10 % over 10,000,000 a month | Income Tax (Amendment) Act, 2026 (assented 20 Aug 2026, effective 1 Jul 2026); assignment brief; [KAA tax alert](https://www.kaa.co.ug/kaa-tax-alert-income-tax-amendment-act-2026/) |
| PAYE, resident, before 1 Jul 2026 | Nil to 235,000; 10 % to 335,000; 20 % to 410,000; 30 % above; +10 % over 10,000,000 | [URA PAYE rates](https://ura.go.ug/en/domestic-taxes/paye-rates/) |
| PAYE, non-resident | 10 % to 335,000; 20 % to 410,000; 30 % above; +10 % over 10,000,000 | [URA PAYE rates](https://ura.go.ug/en/domestic-taxes/paye-rates/) |
| NSSF | Employee 5 %, employer 10 % of gross | Assignment brief |
| Local Service Tax | 5,000 to 100,000 a year by income bracket; four instalments July to October; deducted before PAYE | [KCCA LST FAQs](https://www.kcca.go.ug/uDocs/Local_Service_Tax_FAQs.pdf) |
| VAT | 18 % standard; zero-rated; exempt; input-tax apportionment | [PwC Tax Summaries, Uganda](https://taxsummaries.pwc.com/uganda/corporate/other-taxes) |
| Corporate income tax | 30 % of chargeable income | [PwC Tax Summaries, Uganda](https://taxsummaries.pwc.com/uganda/corporate/taxes-on-corporate-income) |
| Dividend withholding tax | 15 %, final for resident individuals | [PwC Tax Summaries, Uganda](https://taxsummaries.pwc.com/uganda/corporate/withholding-taxes) |

When checked, URA's PAYE rates page still listed the pre-July-2026 resident bands. Both versions are implemented as dated schedules. _[Re-check the URA page before submitting and update this note.]_

## Weather data sources and terms

- [Open-Meteo](https://open-meteo.com/) geocoding and forecast: data under CC BY 4.0; free tier for non-commercial use only (10,000 calls a day); place names from GeoNames.
- [MET Norway Locationforecast 2.0](https://api.met.no/weatherapi/locationforecast/2.0/documentation): CC BY 4.0 / NLOD 2.0; requires an identifying User-Agent with contact details.

No wrapper library is used for either API: all HTTP calls are made directly with `urllib` or `requests`.

## Testing

`pytest -q` runs 109 tests offline:

- weather parsing against the saved sample JSON, and the retry wrapper against a fake session (33 tests);
- `Money` (11), PAYE boundary tests at every band edge of all three schedules (31), property-based tests with hypothesis (5: tax is non-negative, never exceeds income, and is monotonic in income), payroll, LST, VAT and corporate tax (24), and the tax planner (5).

## AI use declaration

> 
> An AI assistant (Claude, by Anthropic) was used to help produce this repository. It drafted the module code, unit tests, notebooks and the first drafts of the written sections, and looked up the tax rates and API terms cited above. I reviewed all of the code, ran the tests and both notebooks myself with a live internet connection and my own contact email, checked the tax results by hand, re-confirmed the tax rates against URA, and rewrote the Part D report and the discussion answers in my own words.  I can explain every part of the code.
