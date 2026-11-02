"""Account HTTP response policy and trusted-proxy address extraction."""
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}


def client_address(request, *, trust_forwarded):
    forwarded = request.headers.get('x-forwarded-for')
    if trust_forwarded and forwarded:
        return forwarded.split(',')[-1].strip()
    return request.client.host if request.client else ''
