import pyramid.util
maybe_resolve = pyramid.util.DottedNameResolver(None).maybe_resolve


def update_dict(parser, section, d):
    '''Update the given dictionary, d, with all keys/values
    from the section in the config parser specified.
    '''

    if parser.has_section(section):
        for k in parser.options(section):
            d[k] = parser.get(section, k)
    return d

try:
    import rfoo
    has_rfoo = True
except:
    has_rfoo = False
