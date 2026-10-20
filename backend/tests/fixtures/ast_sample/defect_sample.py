"""Known-defect test fixture for Week 2 Day 3 AST Rule Integration and Bug Detection.

Contains deterministic structural defects across all supported categories:
- Resource leak (unclosed open call)
- Swallowed exception (bare except with pass)
- Mutable default arguments
- Null/None dereference traps
- Collection mutation during iteration
- Identical if/else branches and duplicate elif conditions
- Unreachable dead code after return
- Dynamic execution with eval
- Self-assignment and self-comparison
- Off-by-one array indexing
"""

import socket


def unclosed_resource_defect(path: str):
    # AST-RES-001: Unclosed resource
    f = open(path, "w")
    f.write("data")
    return True


def swallowed_exception_defect():
    # AST-EXC-001: Bare except pass
    try:
        x = 1 / 0
    except:
        pass


def mutable_default_defect(items=[], config={}):
    # AST-ARG-001: Mutable default argument
    items.append("defect")
    return items


def null_dereference_defect(user=None):
    # AST-NULL-001: Null dereference inside None check and == None check
    if user == None:
        return None
    if user is None:
        return user.profile
    return user.name


def iteration_mutation_defect(records: list):
    # AST-ITER-001: Collection mutation during iteration
    for rec in records:
        if rec == "invalid":
            records.remove(rec)
    return records


def identical_branches_defect(mode: int):
    # AST-LOGIC-001: Identical branches and duplicate elif condition
    if mode == 1:
        return "active"
    elif mode == 1:
        return "active"
    else:
        return "active"


def dead_code_defect(value: int):
    # AST-DEAD-001: Unreachable code after return
    return value * 2
    unreachable_calc = value + 10
    print(unreachable_calc)


def dangerous_eval_defect(payload: str):
    # AST-SEC-001: Dangerous dynamic execution
    result = eval(payload)
    return result


def self_comparison_defect(score: int):
    # AST-LOGIC-002: Self-assignment and tautological comparison
    score = score
    if score == score:
        return True
    return False


def off_by_one_defect(elements: list):
    # AST-BOUND-001: Off-by-one indexing with len()
    last = elements[len(elements)]
    return last
