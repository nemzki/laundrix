"""SMS notifications via UniSMS. `provider.py` talks to UniSMS only; `services.py` holds the rules
(consent, duplicate prevention, retries, status refresh); `phone.py` validates Philippine numbers.
Order routes and templates never parse provider responses."""
