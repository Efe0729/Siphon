

def test_no_error_handler_reads_its_exception_too_late():
    """Python clears the name bound by ``except ... as exc`` as soon as the
    block ends.  A lambda that reads it afterwards — to show the message on
    the interface thread — raises NameError, so the person is shown that
    instead of what actually went wrong, exactly when something has already
    failed.  Binding it as a default argument captures it at once.

    This is a whole-file check rather than one case, because the mistake
    looks completely ordinary and would come back.
    """
    import ast
    import pathlib

    source = pathlib.Path(
        __file__).resolve().parents[1] / 'src' / 'siphon' / 'apps' / 'upload_tab.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))

    late = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not node.name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, (ast.Lambda, ast.FunctionDef)):
                continue
            bound_now = [d for d in list(child.args.defaults)
                         + [k for k in child.args.kw_defaults if k]]
            for inner in ast.walk(child):
                if (isinstance(inner, ast.Name) and inner.id == node.name
                        and isinstance(inner.ctx, ast.Load)
                        and not any(inner is seen for default in bound_now
                                    for seen in ast.walk(default))):
                    late.append(f'line {inner.lineno}: reads "{node.name}"')

    assert not late, (
        'these run after their except block has ended and will raise '
        'NameError: ' + '; '.join(late))
