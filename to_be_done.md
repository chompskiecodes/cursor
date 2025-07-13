# TO BE DONE

## API Response Standardization

- **Reminder:**
  - Eventually standardize on a single response key for available times (preferably `available_times`).
  - Remove the legacy `slots` key from all API endpoints, clients, and tests **after** all consumers have been updated to use `available_times` only.
  - This will reduce duplication and improve API clarity.

- **Steps:**
  1. Audit all API endpoints for `slots`/`available_times` usage.
  2. Update all client code and test scripts to use only `available_times`.
  3. Remove `slots` from all API responses and code.
  4. Update documentation to reflect the change. 

## Cliniko API Limitation: Practitioner & Business Hours

- **Based on research of the Cliniko API documentation:**
  - There is **no dedicated API endpoint** for retrieving practitioner working hours or business operating hours.
  - The API only provides:
    - **Available times endpoint** – Returns unbooked appointment slots
    - **Appointments endpoint** – Returns booked appointments
    - **Business settings** – Basic business information but not operating hours

- **Confirmed Limitation:**
  - The Cliniko API does **not** expose:
    - Practitioner work schedules
    - Business operating hours
    - Days when practitioners are working but fully booked

- **Recommended Solution:**
  - Since the API doesn't provide this information, here's the best approach to distinguish between "working but fully booked" and "not working":

  ### Store Working Hours Locally
  - Maintain practitioner schedules in your own database. Example schema:

    ```sql
    CREATE TABLE practitioner_schedules (
        practitioner_id TEXT,
        business_id TEXT,
        day_of_week INT, -- 0-6 (Sunday-Saturday)
        start_time TIME,
        end_time TIME,
        effective_from DATE,
        effective_until DATE,
        PRIMARY KEY (practitioner_id, business_id, day_of_week, effective_from)
    );
    ```
  - This allows you to definitively know when practitioners are scheduled to work, regardless of their booking status. 

## Efficient Multi-Day Cache Queries for Availability

- **Motivation:**
  - The current cache logic only supports single-day lookups for practitioner/business availability, mirroring the limitations of the Cliniko API. This results in slow, repetitive queries when a week or more of availability is needed.
  - The cache is stored in a database and can be queried much more flexibly and efficiently than the API.

- **Current Limitation:**
  - All endpoints and utilities loop over each day, calling the cache (and possibly the API) for each day separately. This is inefficient and unnecessary when the cache already contains the data for a range of days.

- **Planned Upgrade:**
  1. Add a new method to the cache manager to fetch all cached slots for a practitioner/business over a date range (e.g., a week) in a single query.
  2. Update cache utility functions to use this new method and aggregate results for multi-day requests.
  3. Refactor endpoints and managers (including parallel/enhanced logic) to use batch cache queries for week/multi-day requests, instead of looping per day.
  4. Only fall back to the API for days not present in the cache, and update the cache accordingly.
  5. Update/add tests to ensure correct aggregation and performance for week/multi-day cache queries.

- **Expected Benefit:**
  - Dramatically faster week/multi-day availability lookups, with no changes to the slow, limited Cliniko API logic.
  - Reduced database and API load, and improved user experience for all clients. 