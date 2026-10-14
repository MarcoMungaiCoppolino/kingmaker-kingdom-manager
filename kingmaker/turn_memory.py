"""What the kingdom remembers from one Kingdom turn to the next.

The rules that carry across turns, kept in `k["turn_memory"]`:

- `record`: who attempted what, where and with which result, for the last
  three turns (history only: nothing below is rebuilt from it);
- `last`: the turn each activity was last attempted (Rest and Relax and
  Celebrate Holiday cost more when repeated the next turn);
- `streaks`: Clandestine Business's DC, +2 per consecutive turn, -1 per turn
  without, down to the Control DC;
- `lockouts`: activities that cannot be attempted until a turn (Repair
  Reputation on a Ruin, an envoy to a group, Supernatural Solution, ...);
- `debts`: Tap Treasury's, until Capital Investment repays it;
- `penalties`: bonuses and penalties bound to a leader, a partner or the
  whole kingdom, with when they end (New Leadership's failure, an envoy's
  retry, a leader's downtime missed);
- `pending`: the flat checks rolled at the next Event phase (Abandon Hex's
  Squatters, Establish Farmland's Crop Failure, Irrigation's Plague).

Invariant: every structure but `record` is written by the outcome row itself
and never rebuilt from the record, so trimming the record to three turns can
never lose a lock-out, a debt, a penalty or a pending check.

Pure functions over the kingdom document; `State` wraps them, and the
interface calls `STATE.*` only.
"""
from __future__ import annotations

# How many turns of history the record keeps: this one and the two before.
RECORD_TURNS = 3

EMPTY = {"record": [], "last": {}, "streaks": {}, "lockouts": [],
         "debts": {}, "penalties": [], "pending": []}


def memory(k: dict) -> dict:
    """The kingdom's `turn_memory`, every sub-key present."""
    mem = k.setdefault("turn_memory", {})
    for key, empty in EMPTY.items():
        if key not in mem:
            mem[key] = type(empty)()
    return mem


# ------------------------------------------------------------- the record
def record_activity(k: dict, act: str, *, role=None, character=None, settlement=None,
                    hex_=None, skill=None, subject=None) -> None:
    mem = memory(k)
    mem["record"].append({"turn": k["turn"], "act": act, "role": role, "character": character,
                          "settlement": settlement, "hex": list(hex_) if hex_ else None,
                          "skill": skill, "grade": None, "subject": subject})
    mem["last"][act] = k["turn"]


def note_grade(k: dict, act: str, grade: str) -> None:
    """The result of the latest attempt of `act` this turn."""
    for row in reversed(memory(k)["record"]):
        if row["act"] == act and row["turn"] == k["turn"]:
            row["grade"] = grade
            return


def repeated(k: dict, act: str) -> bool:
    """Attempted in the turn before this one. Asked after this turn's attempt
    too (an outcome's «if you did it last turn» rows), when `last` already
    holds this turn: the record still holds last turn's."""
    mem = memory(k)
    return (mem["last"].get(act) == k["turn"] - 1
            or any(r["act"] == act and r.get("turn") == k["turn"] - 1 for r in mem["record"]))


# ------------------------------------------------------------- streaks
def streak_dc(k: dict, act: str, data: dict | None) -> int:
    """The DC increase of an activity with a streak (`{"per_turn", "decay"}`):
    the increase of its last attempt, `per_turn` more when that was last turn,
    `decay` less for each turn without one since, never below 0. `value` is
    the increase the last attempt was made with."""
    if not data:
        return 0
    entry = memory(k)["streaks"].get(act)
    if not entry:
        return 0
    gap = k["turn"] - entry["last_turn"]
    if gap <= 0:
        return entry["value"]
    if gap == 1:
        return entry["value"] + data["per_turn"]
    return max(0, entry["value"] - data["decay"] * (gap - 1))


def bump_streak(k: dict, act: str, data: dict) -> None:
    """Attempted this turn, with the increase `streak_dc` gives now. Twice in
    one turn counts once."""
    entry = memory(k)["streaks"].get(act)
    if entry and entry["last_turn"] == k["turn"]:
        return
    memory(k)["streaks"][act] = {"value": streak_dc(k, act, data), "last_turn": k["turn"]}


# ------------------------------------------------------------- lock-outs
def lockout(k: dict, act: str, subject=None) -> dict | None:
    """The lock-out that bars `act` now: on `subject`, or on everything. With
    `subject` None, only a lock-out on the whole activity counts (a card on
    the Turn tab is dimmed by those alone)."""
    for entry in memory(k)["lockouts"]:
        if entry["act"] != act or k["turn"] > entry["until_turn"]:
            continue
        if entry.get("subject") is None or (subject is not None and entry["subject"] == subject):
            return entry
    return None


def add_lockout(k: dict, act: str, subject, turns: int, reason: str) -> None:
    """«You cannot attempt it for N Kingdom turns»: the N turns after this one."""
    memory(k)["lockouts"].append({"act": act, "subject": subject,
                                  "until_turn": k["turn"] + max(1, turns), "reason": reason})


# ------------------------------------------------------------- debts
def debt(k: dict, key: str) -> dict | None:
    return memory(k)["debts"].get(key)


# ------------------------------------------------------------- penalties
def penalty_active(k: dict, entry: dict) -> bool:
    return entry.get("until_turn") is None or k["turn"] <= entry["until_turn"]


def active_penalties(k: dict, *, role=None, subject=None, phase=None) -> list[dict]:
    """The penalties (and bonuses) that reach a check now: a leader's when
    that leader acts (and, when the entry names a phase, in that phase), a
    partner's when the check is about that partner, the kingdom's always."""
    out = []
    for entry in memory(k)["penalties"]:
        if not penalty_active(k, entry):
            continue
        scope = entry.get("scope")
        if scope == "leader":
            if role is None or entry.get("role") != role:
                continue
            if entry.get("phase") and phase is not None and entry["phase"] != phase:
                continue
            if entry.get("phase") and phase is None:
                continue
        elif scope == "partner":
            if subject is None or entry.get("subject") != subject:
                continue
        elif scope != "kingdom":
            continue
        out.append(entry)
    return out


# ------------------------------------------------------------- pending checks
def due_checks(k: dict) -> list[dict]:
    """The flat checks to roll in this turn's Event phase."""
    return [e for e in memory(k)["pending"] if e.get("due_turn") is not None
            and e["due_turn"] <= k["turn"]]


# ------------------------------------------------------------- the boundary
def new_turn(k: dict) -> None:
    """A new Kingdom turn has begun (`k["turn"]` already moved on): the record
    trimmed to three turns, expired lock-outs and penalties dropped, the
    penalties that last «until next turn» gone. Pending checks are rolled,
    never expired; streaks decay by themselves (`streak_dc`)."""
    mem = memory(k)
    turn = k["turn"]
    mem["record"] = [r for r in mem["record"] if r.get("turn", 0) >= turn - (RECORD_TURNS - 1)]
    mem["lockouts"] = [e for e in mem["lockouts"] if e["until_turn"] >= turn]
    mem["penalties"] = [e for e in mem["penalties"]
                        if (e.get("until_turn") is None or e["until_turn"] >= turn)
                        and not (e.get("clears_on") == "next_turn" and e.get("since_turn", turn) < turn)]
