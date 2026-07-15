import requests
import gspread
import time

from datetime import datetime, timedelta, UTC
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================================
# CONFIG
# ==========================================================

SHEET_ID = "12YwYzJAvmgToAcEAm1iqcsyBGj_8m2dvKABN-_z56Yc"
CREDENTIALS_FILE = "credentials.json"

REQUEST_TIMEOUT = 20
RETRY_COUNT = 3
RETRY_DELAY = 2

# ==========================================================
# HELPERS
# ==========================================================

def safe_int(value):
    try:
        return int(str(value).strip())
    except:
        return 0


def col_to_letter(col):

    result = ""

    while col > 0:
        col, rem = divmod(col - 1, 26)
        result = chr(65 + rem) + result

    return result


def parse_today_cell(cell):

    if not cell:
        return 0, 0, 0, 0

    cell = cell.strip()

    if cell == "" or cell.upper() == "ERR":
        return 0, 0, 0, 0

    try:

        total_part, rest = cell.split(" ", 1)

        total = int(total_part)

        rest = rest.strip()[1:-1]

        e, m, h = rest.split("/")

        return (
            safe_int(total),
            safe_int(e),
            safe_int(m),
            safe_int(h)
        )

    except:
        return 0, 0, 0, 0


# ==========================================================
# DATE (IST)
# ==========================================================

def get_today():

    utc = datetime.now(UTC)

    ist = utc + timedelta(hours=5, minutes=30)

    if ist.hour < 2:
        ist -= timedelta(days=1)

    return ist.strftime("%Y-%m-%d")


# ==========================================================
# LEETCODE API
# ==========================================================

GRAPHQL_URL = "https://leetcode.com/graphql"

GRAPHQL_QUERY = """
query($u:String!){
  matchedUser(username:$u){
    submitStats{
      acSubmissionNum{
        difficulty
        count
      }
    }
  }
}
"""


def get_stats(username):

    for attempt in range(RETRY_COUNT):

        try:

            response = requests.post(
                GRAPHQL_URL,
                json={
                    "query": GRAPHQL_QUERY,
                    "variables": {
                        "u": username
                    }
                },
                timeout=REQUEST_TIMEOUT
            )

            data = response.json()

            user = data.get("data", {}).get("matchedUser")

            if not user:
                return None

            stats = user["submitStats"]["acSubmissionNum"]

            easy = next(
                (
                    x["count"]
                    for x in stats
                    if x["difficulty"] == "Easy"
                ),
                0
            )

            medium = next(
                (
                    x["count"]
                    for x in stats
                    if x["difficulty"] == "Medium"
                ),
                0
            )

            hard = next(
                (
                    x["count"]
                    for x in stats
                    if x["difficulty"] == "Hard"
                ),
                0
            )

            return {
                "easy": safe_int(easy),
                "medium": safe_int(medium),
                "hard": safe_int(hard),
                "total": safe_int(easy + medium + hard)
            }

        except Exception:

            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY)

    return None


# ==========================================================
# GOOGLE SHEETS
# ==========================================================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

client = gspread.authorize(
    ServiceAccountCredentials.from_json_keyfile_name(
        CREDENTIALS_FILE,
        scope
    )
)

sheet = client.open_by_key(SHEET_ID).sheet1
# ==========================================================
# LOAD SHEET
# ==========================================================

today = get_today()

values = sheet.get_all_values()

header = values[0]

# ----------------------------------------------------------
# Create today's column if it doesn't exist
# ----------------------------------------------------------

if today not in header:

    header.append(today)

    sheet.update(
        range_name="1:1",
        values=[header]
    )

    values = sheet.get_all_values()
    header = values[0]

# ----------------------------------------------------------
# Column indexes
# ----------------------------------------------------------

idx_name = header.index("Name") + 1
idx_user = header.index("LeetCodeUsername") + 1
idx_baseline = header.index("BaselineTotal") + 1
idx_total = header.index("TotalSolved") + 1

idx_prev_easy = header.index("PrevEasy") + 1
idx_prev_medium = header.index("PrevMedium") + 1
idx_prev_hard = header.index("PrevHard") + 1
idx_prev_total = header.index("PrevTotal") + 1

today_col = header.index(today) + 1

# ----------------------------------------------------------
# Lists for batch update
# ----------------------------------------------------------

today_values = []

new_prev = []

new_total = []

# ----------------------------------------------------------
# Counters
# ----------------------------------------------------------

updated = 0
unchanged = 0
failed = 0
recovered = 0

print("=" * 60)
print(f"📅 DAILY UPDATE : {today}")
print("=" * 60)

# ==========================================================
# START PROCESSING
# ==========================================================

for row_number, row in enumerate(values[1:], start=2):

    def cell(col):

        idx = col - 1

        if idx >= len(row):
            return ""

        return row[idx]

    name = cell(idx_name).strip()
    username = cell(idx_user).strip()

    # ------------------------------------------------------
    # Skip blank rows
    # ------------------------------------------------------

    if username == "":

        today_values.append([""])
        new_prev.append(["", "", "", ""])
        new_total.append([""])

        continue

    # ------------------------------------------------------
    # Skip section headings
    # ------------------------------------------------------

    if username.lower() == "leetcodeusername":

        today_values.append([""])
        new_prev.append(["", "", "", ""])
        new_total.append([""])

        continue

    baseline = safe_int(cell(idx_baseline))

    prev_easy = safe_int(cell(idx_prev_easy))
    prev_medium = safe_int(cell(idx_prev_medium))
    prev_hard = safe_int(cell(idx_prev_hard))
    prev_total = safe_int(cell(idx_prev_total))

    total_sheet = safe_int(cell(idx_total))

    existing_today = cell(today_col)

    old_total, old_easy, old_medium, old_hard = parse_today_cell(
        existing_today
    )

    stats = get_stats(username)

    # ------------------------------------------------------
    # API failed
    # ------------------------------------------------------

    if stats is None:

        failed += 1

        today_values.append([
            existing_today if existing_today else "ERR"
        ])

        new_prev.append([
            prev_easy,
            prev_medium,
            prev_hard,
            prev_total
        ])

        new_total.append([
            total_sheet
        ])

        print(f"❌ {username}")

        continue

    easy_now = stats["easy"]
    medium_now = stats["medium"]
    hard_now = stats["hard"]
    total_now = stats["total"]

    # ------------------------------------------------------
    # Detect recovery
    # ------------------------------------------------------

    if total_now > total_sheet:

        recovered += 1

        print(
            f"🔄 Recovering {username} "
            f"({total_sheet} → {total_now})"
        )

    delta_easy = max(easy_now - prev_easy, 0)
    delta_medium = max(medium_now - prev_medium, 0)
    delta_hard = max(hard_now - prev_hard, 0)
    delta_total = max(total_now - prev_total, 0)

    # ------------------------------------------------------
    # Student solved new problems
    # ------------------------------------------------------

    if delta_total > 0:

        # If today's cell already contains progress,
        # continue from that value instead of overwriting.

        new_today_total = old_total + delta_total
        new_today_easy = old_easy + delta_easy
        new_today_medium = old_medium + delta_medium
        new_today_hard = old_hard + delta_hard

        today_string = (
            f"{new_today_total} "
            f"({new_today_easy}/{new_today_medium}/{new_today_hard})"
        )

        today_values.append([today_string])

        updated += 1

        print(
            f"✅ {username:<30}"
            f"+{delta_total:<3}"
            f" ({delta_easy}/{delta_medium}/{delta_hard})"
        )

    else:

        # Keep today's previous value if script
        # is executed multiple times.

        if existing_today:

            today_values.append([existing_today])

        else:

            today_values.append(["0 (0/0/0)"])

        unchanged += 1

        print(f"➖ {username}")

    # ------------------------------------------------------
    # Store latest stats
    # ------------------------------------------------------

    new_prev.append([
        easy_now,
        medium_now,
        hard_now,
        total_now
    ])

    new_total.append([
        total_now
    ])

    # ------------------------------------------------------
    # Prevent LeetCode rate limit
    # ------------------------------------------------------

    time.sleep(0.8)
    # ==========================================================
# BATCH UPDATE GOOGLE SHEET
# ==========================================================

last_row = len(values)

today_letter = col_to_letter(today_col)

total_letter = col_to_letter(idx_total)

prev_start = col_to_letter(idx_prev_easy)
prev_end = col_to_letter(idx_prev_total)

print("\n📤 Updating Google Sheet...\n")

# ----------------------------------------------------------
# Today's Progress
# ----------------------------------------------------------

sheet.update(
    range_name=f"{today_letter}2:{today_letter}{last_row}",
    values=today_values
)

# ----------------------------------------------------------
# Previous Stats
# ----------------------------------------------------------

sheet.update(
    range_name=f"{prev_start}2:{prev_end}{last_row}",
    values=new_prev
)

# ----------------------------------------------------------
# Current TotalSolved
# ----------------------------------------------------------

sheet.update(
    range_name=f"{total_letter}2:{total_letter}{last_row}",
    values=new_total
)

print("✅ Google Sheet Updated Successfully")

# ==========================================================
# SUMMARY
# ==========================================================

print("\n" + "=" * 65)
print("                DAILY UPDATE SUMMARY")
print("=" * 65)

print(f"📅 Date               : {today}")
print(f"✅ Updated Students   : {updated}")
print(f"➖ No Changes         : {unchanged}")
print(f"🔄 Recovered          : {recovered}")
print(f"❌ Failed             : {failed}")
print(f"👨‍🎓 Total Processed   : {updated + unchanged + failed}")

print("=" * 65)
print("🎉 Daily Update Completed Successfully!")
print("=" * 65)