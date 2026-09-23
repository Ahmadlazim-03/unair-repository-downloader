# Repository intermediate certificate

`sectigo-dv-r36.pem` is the public Sectigo Public Server Authentication CA DV R36
intermediate. It contains no private key.

- Official AIA source: http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt
- SHA-256 of DER: `8c54c334b66ba4e426772af4a3f9136c19a1aec729fdb28c535c07a5a4ef22e0`
- Issuer: Sectigo Public Server Authentication Root R46.
- Valid through 2036-03-21.
- Its signature/chain was verified with OpenSSL against the certifi public root bundle.

Observed 2026-09-23 through an authenticated campus WireGuard connection:
`ir.unair.ac.id` served a `*.unair.ac.id` leaf issued by DV R36, together with the
unrelated older Sectigo RSA Domain Validation Secure Server CA intermediate.
Python/OpenSSL could not build the chain (`unable to get local issuer certificate`).

The application supplies the correct intermediate only for the repository host,
while retaining hostname/date verification and requiring a full chain to a
trusted root. `VERIFY_X509_PARTIAL_CHAIN` is explicitly disabled. The app does not
download certificates at runtime or trust the leaf certificate directly.
