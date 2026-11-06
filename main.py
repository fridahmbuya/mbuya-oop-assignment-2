import requests

url = "https://api.open-meteo.com/v1/forecast"

params = {
    "latitude": 0.3476,
    "longitude": 32.5825,
    "daily": [
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum"
    ],
    "timezone": "Africa/Kampala",
    "forecast_days": 5
}

response = requests.get(
    url,
    params=params,
    timeout=10
)

response.raise_for_status()

data = response.json()

import pandas as pd

daily_data = data["daily"]

df = pd.DataFrame(daily_data)

print(df)