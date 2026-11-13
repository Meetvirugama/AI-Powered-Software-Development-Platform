# Fix greedy regex match in tag stripper

re.sub('<.*>', '', text) strips all content between first open and last close tag.
