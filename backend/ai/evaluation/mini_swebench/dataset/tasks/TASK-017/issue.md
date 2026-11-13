# Catch specific FileNotFoundError instead of broad exception

read_text_safely should handle missing file cleanly without catching KeyboardInterrupt.
