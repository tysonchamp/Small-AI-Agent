import dateparser
from datetime import datetime

time_str = "every 30 seconds"
dt = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
print(f"Input: '{time_str}'")
print(f"Parsed: {dt}")

time_str_2 = "in 30 seconds"
dt_2 = dateparser.parse(time_str_2, settings={'PREFER_DATES_FROM': 'future'})
print(f"Input: '{time_str_2}'")
print(f"Parsed: {dt_2}")
