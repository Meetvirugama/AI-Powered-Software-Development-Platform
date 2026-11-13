# Parse ISO datetime strings with Z suffix

fromisoformat in older versions fails on trailing Z. Replace Z with +00:00.
