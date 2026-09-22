import tree_sitter_languages

def test_tree_sitter():
    parser = tree_sitter_languages.get_parser("python")
    code = b'''
def hello_world():
    print("Hello, world!")
'''
    tree = parser.parse(code)
    print(tree.root_node.sexp())

if __name__ == "__main__":
    test_tree_sitter()
