from timestamps import adjust_timestamp
assert adjust_timestamp(1000, 500) == 1500
assert adjust_timestamp(1000, -500) == 500
