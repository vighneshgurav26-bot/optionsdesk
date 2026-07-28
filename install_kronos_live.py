"""
install_kronos_live.py

Runs ONCE (triggered by the install-kronos-live workflow) to wire Kronos
into whatever strategy your bot is running RIGHT NOW, stored in
state/desk.db.

SAFETY RULES this script follows, on purpose:
  1. It only ever ADDS to an "any" list. It never touches "all" or "none"
     rules, never touches sizing/risk/session settings. Those keep working
     exactly as they do today.
  2. An "any" list only needs ONE of its conditions to be true - so adding
     one more condition to it can only make trades MORE likely, never less.
  3. It makes a timestamped backup copy of desk.db before changing anything.
  4. If it can't find a recognisable strategy in the database, it changes
     NOTHING and just prints a message - it never guesses or forces a change.
"""
import json
import shutil
import sqlite3
import sys
import time

DB_PATH = "state/desk.db"


def backup_db(path: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.before_kronos_{stamp}.bak"
    shutil.copyfile(path, backup_path)
    return backup_path


def find_strategy_cells(conn: sqlite3.Connection):
    """Look through every table/column for text that looks like a strategy
    spec (contains the key "entry_long_call"). Returns a list of
    (table, column, rowid, current_json_text)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    hits = []
    for t in tables:
        cur.execute(f"PRAGMA table_info('{t}')")
        cols = [r[1] for r in cur.fetchall()]
        for col in cols:
            try:
                cur.execute(f"SELECT rowid, \"{col}\" FROM \"{t}\"")
                rows = cur.fetchall()
            except sqlite3.OperationalError:
                continue
            for rowid, val in rows:
                if isinstance(val, str) and '"entry_long_call"' in val:
                    hits.append((t, col, rowid, val))
    return hits


def add_kronos_any_clause(spec_json: str):
    """Returns (new_json_text, changed_bool, notes_list)."""
    spec = json.loads(spec_json)
    changed = False
    notes = []
    pairs = [("entry_long_call", "kronos_bull_score"),
             ("entry_long_put", "kronos_bear_score")]
    for key, feature in pairs:
        node = spec.get(key)
        if not isinstance(node, dict):
            notes.append(f"no '{key}' block found - skipped")
            continue
        anys = node.setdefault("any", [])
        cond = {"feature": feature, "op": ">", "value": 0.5}
        if cond in anys:
            notes.append(f"'{key}' already has the kronos clause - left as is")
            continue
        anys.append(cond)
        changed = True
        notes.append(f"'{key}': added any-clause {cond}")
    return json.dumps(spec), changed, notes


def main():
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.OperationalError as e:
        print(f"Could not open {DB_PATH}: {e}. Nothing changed.")
        sys.exit(0)

    hits = find_strategy_cells(conn)
    if not hits:
        print("No live strategy found inside desk.db (no cell containing "
              "'entry_long_call'). Nothing changed - safe no-op.")
        conn.close()
        return

    backup_path = backup_db(DB_PATH)
    print(f"Backed up desk.db to {backup_path} before making any change.")

    any_changed = False
    for table, col, rowid, val in hits:
        new_val, changed, notes = add_kronos_any_clause(val)
        for n in notes:
            print(f"  [{table}.{col} row {rowid}] {n}")
        if changed:
            conn.execute(
                f'UPDATE "{table}" SET "{col}" = ? WHERE rowid = ?',
                (new_val, rowid))
            any_changed = True

    if any_changed:
        conn.commit()
        print("Done. Kronos is now one extra 'any' vote in the live "
              "strategy - it can only add trade opportunities, never "
              "remove any that already exist.")
    else:
        print("Nothing needed changing (already applied, or no matching "
              "block found).")
    conn.close()


if __name__ == "__main__":
    main()
