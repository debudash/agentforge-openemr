"""Book the co-pilot's rounding list: N appointments per doctor, for one or more days.

The co-pilot's rounding list is "today's appointments booked for the signed-in provider,
restricted to that provider's assigned patients". The Synthea dataset has no calendar
events, so this creates them. Writes go through POST /api/patient/:pid/appointment, so
OpenEMR's validation and audit logging run (AUDIT.md C1b).

Idempotent per day: this script's own bookings for each target date are removed first
(only those titled "Rounding (co-pilot demo)"), then recreated from 08:00 at 15-minute
intervals. Re-running never duplicates.

Dates default to the **server's** current date, which is UTC in the containers and can
differ from the host's local date late in the day.

Laptop use, local stack:
    cd usecases
    $env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"
    .venv\\Scripts\\python ..\\scripts\\seed_appointments.py

Laptop use, Railway:
    $env:OPENEMR_BASE_URL="https://<app>.up.railway.app"; $env:OE_PASS="<admin pw>"
    $env:OE_DB_VIA="railway"; $env:OE_DB_PASS="<openemr db pw>"
    .venv\\Scripts\\python ..\\scripts\\seed_appointments.py --days 5

Inside the Railway cron container: OE_DB_VIA=mysql with MYSQL_* set; every option also
reads an environment variable, so no arguments are needed.

@package   OpenEMR
@author    Debu Dash
@copyright Copyright (c) 2026 Debu Dash
@license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oe_api import READ_SCOPES, REST, api_session, db_query  # noqa: E402

TITLE = "Rounding (co-pilot demo)"
WRITE_SCOPES = READ_SCOPES + ["user/appointment.read", "user/appointment.write"]


def parse_args() -> argparse.Namespace:
    import os

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Five per doctor is the demo list size (USER.md §1.1): a real hospitalist carries 12-18,
    # but each patient costs a prefetched brief, so the demo trades census for time and cost.
    parser.add_argument("--per-doctor", type=int, default=int(os.environ.get("SEED_PER_DOCTOR", "5")))
    parser.add_argument("--days", type=int, default=int(os.environ.get("SEED_DAYS", "1")),
                        help="how many consecutive days to seed, starting at --date")
    parser.add_argument("--date", default=os.environ.get("SEED_START_DATE") or None,
                        help="YYYY-MM-DD; default is the OpenEMR server's current date")
    parser.add_argument("--category", type=int, default=int(os.environ.get("SEED_CATEGORY", "5")),
                        help="pc_catid (5 = Office Visit)")
    parser.add_argument("--start-time", default=os.environ.get("SEED_START_TIME", "08:00"))
    parser.add_argument("--slot-minutes", type=int, default=int(os.environ.get("SEED_SLOT_MINUTES", "15")))
    return parser.parse_args()


def seed_one_day(session, date: str, doctors: dict[str, int], facility: int, args: argparse.Namespace) -> int:
    removed = db_query(
        f"SELECT COUNT(*) FROM openemr_postcalendar_events WHERE pc_title = '{TITLE}' AND pc_eventDate = '{date}'"
    )[0][0]
    db_query(f"DELETE FROM openemr_postcalendar_events WHERE pc_title = '{TITLE}' AND pc_eventDate = '{date}'")
    print(f"{date}: removed {removed} existing booking(s)")

    booked = 0
    for username, user_id in doctors.items():
        pids = [int(row[0]) for row in db_query(
            f"SELECT pid FROM patient_data WHERE providerID = {user_id} ORDER BY pid LIMIT {args.per_doctor}")]
        slot = dt.datetime.fromisoformat(f"{date}T{args.start_time}")
        for pid in pids:
            response = session.post(f"{REST}/patient/{pid}/appointment", timeout=90, json={
                "pc_catid": args.category, "pc_title": TITLE,
                "pc_duration": args.slot_minutes * 60,
                "pc_hometext": "Booked by scripts/seed_appointments.py for the co-pilot demo",
                "pc_apptstatus": "-", "pc_eventDate": date,
                "pc_startTime": slot.strftime("%H:%M"),
                "pc_facility": facility, "pc_billing_location": facility, "pc_aid": user_id,
            })
            if response.status_code == 200:
                booked += 1
            else:
                print(f"  FAILED {username} pid={pid}: {response.status_code} {response.text[:160]}")
            slot += dt.timedelta(minutes=args.slot_minutes)
        print(f"  {username} (id {user_id}): {len(pids)} patient(s)")
    return booked


def main() -> int:
    args = parse_args()

    doctors = {row[1]: int(row[0]) for row in db_query(
        "SELECT id, username FROM users WHERE username IN ('doctor1','doctor2') ORDER BY username")}
    assert set(doctors) == {"doctor1", "doctor2"}, f"expected both doctors, got {doctors}"
    facility = int(db_query("SELECT id FROM facility ORDER BY id LIMIT 1")[0][0])

    start = dt.date.fromisoformat(args.date) if args.date else dt.date.fromisoformat(db_query("SELECT CURDATE()")[0][0])
    dates = [(start + dt.timedelta(days=offset)).isoformat() for offset in range(max(1, args.days))]
    print(f"seeding {len(dates)} day(s) from {dates[0]} ({args.per_doctor} per doctor)")

    total = 0
    # One OAuth client for every day, rather than one per day.
    with api_session(WRITE_SCOPES, client_name="copilot-appointment-seeder") as session:
        for date in dates:
            total += seed_one_day(session, date, doctors, facility, args)
    print(f"total booked: {total}")

    print("--- verification ---")
    rows = db_query(
        f"SELECT e.pc_eventDate, COUNT(DISTINCT e.pc_aid), COUNT(*) FROM openemr_postcalendar_events e "
        f"WHERE e.pc_title = '{TITLE}' AND e.pc_eventDate BETWEEN '{dates[0]}' AND '{dates[-1]}' "
        f"GROUP BY e.pc_eventDate ORDER BY 1")
    expected = args.per_doctor * len(doctors)
    ok = True
    for date, doctor_count, appointment_count in rows:
        flag = "" if int(appointment_count) == expected else "  <-- INCOMPLETE"
        ok = ok and not flag
        print(f"  {date}: {doctor_count} doctor(s), {appointment_count} appointment(s){flag}")
    if len(rows) != len(dates):
        print(f"  WARNING: expected {len(dates)} dates, found {len(rows)}")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
