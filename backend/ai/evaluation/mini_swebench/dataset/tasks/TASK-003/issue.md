# Remove mutable default list argument in add_tag

def add_tag(tag, tags=[]): shares tag list state across multiple calls.
