# Quirebase

A self-hosted collaborative research library. Discover papers, organize references, read and
annotate PDFs together, and take the results into your writing.

[Get started](https://jadeiin.github.io/quirebase/getting-started/quickstart/) ·
[Install Quirebase](https://jadeiin.github.io/quirebase/administration/deployment/) ·
[Documentation](https://jadeiin.github.io/quirebase/)

<picture>
<img alt="Quirebase in action: discover papers, preview a bibliography import, organize references, highlight a PDF, reply to a shared annotation, and export citations." src="https://github.com/user-attachments/assets/7bd512c7-fb0d-48c5-add6-966ca87a7a04" />
</picture>

Quirebase is currently in alpha. APIs, database schemas, and persisted workflow inputs and
checkpoints may change incompatibly between releases. Follow each release's upgrade instructions;
do not assume rolling upgrades or cross-version backup restoration are supported.

## What you can do

- **Build your library.** Search scholarly sources and import references from identifiers,
  bibliography files, or PDFs. Review import previews before saving.
- **Keep research organized.** Use Workspaces, Projects, Tags, and saved Library views to organize
  references for different tasks.
- **Read together.** Highlight PDFs, keep private notes, share Project Annotations, and discuss
  references with colleagues.
- **Bring references into writing.** Copy formatted citations, export bibliographies, and download
  PDF bundles.
- **Connect your tools.** Use the HTTP API and MCP with revocable API Tokens.

## Get started

From a source checkout with Docker Compose, Make, and OpenSSL available:

```sh
make docker-env
make docker-build
make docker-up
make docker-admin
make docker-doctor
```

Open <http://127.0.0.1:9060> and sign in as `admin` with the password you set.
Follow the [installation guide](https://jadeiin.github.io/quirebase/administration/deployment/) for source
installs and HTTPS setup, then [add your first reference](https://jadeiin.github.io/quirebase/getting-started/quickstart/).

## Documentation

| You want to | Read |
| --- | --- |
| Import, organize, read, and collaborate | [User guides](https://jadeiin.github.io/quirebase/getting-started/quickstart/) |
| Configure, back up, or upgrade an installation | [Administration](https://jadeiin.github.io/quirebase/administration/configuration/) |
| Connect a script or client | [HTTP API](https://jadeiin.github.io/quirebase/developers/http-api/) or [MCP](https://jadeiin.github.io/quirebase/developers/mcp/) |
| Explore implementation decisions and contracts | [Engineering documentation](docs/README.md) |

The [documentation project](site/README.md) explains how to preview the guides locally.

## Development

From a checkout, start the development application with:

```sh
./scripts/dev.sh
```

See the [contributor guide](site/src/content/docs/developers/contributing.md) for prerequisites,
development settings, and documentation work. Follow [Testing](docs/TESTING.md) for checks and test
environments. Domain terms and module ownership live in the [glossary](GLOSSARY.md) and
[architecture contracts](docs/architecture/modules.md).

## License

Quirebase is licensed under [AGPL-3.0-only](LICENSE). See [third-party licenses](THIRD_PARTY.md)
for bundled dependencies.
