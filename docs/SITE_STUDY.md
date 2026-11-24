# Site study: www.rmbhimoveis.com.br

I studied the site on 2026-11-24 by driving Chromium with Selenium and recording the
DevTools network log (`tools/network_study.py`). Then I replayed every call
with plain `requests` to confirm that no browser, JavaScript or cookies beyond
`PHPSESSID` are needed.

## Technology

- A server-rendered PHP site (Apache) built on an Imoview CRM theme ("Universal
  Software" footer). jQuery 1.10, Bootstrap 3 and the Owl Carousel and Fancybox plugins.
- **There is no JSON API.** Every response is HTML: either a full page or a small
  fragment injected with jQuery.
- Every response starts with an `<!-- TOKEN:... -->` comment. It is only
  cache-busting noise and is not needed for any request.
- The listing photos are hosted on the Imoview CDN:
  `https://cdn.imoview.com.br/rmimoveis/Imoveis/{code}/{file}?{timestamp}`.
- There are no anti-bot measures (no captcha on reads, no JS challenge, no rate limiting
  observed). The only reCAPTCHA is on the contact forms, which this tool never touches.

## Endpoints

| Purpose | Request | Response |
|---|---|---|
| Property types | `GET /Busca/consulta_tipoimo.php?FINALIDADEIMOVEL={1,2}` | `<option value="{id}">{name}</option>` list mixed with debug text `numero registro: N<br/>` |
| Neighbourhoods | `GET /Busca/consulta_bairros.php?TIPOIMO={id}&FINALIDADEIMOVEL={1,2}` | Table of `<input name="BAIRRO[]" value="{id}"> Name (City - UF)` |
| Start a search | `POST /Busca/tratar_busca.php` with form fields `FINALIDADEIMOVEL, TIPOIMO, QUARTOS, VALORMINIMO, VALORMAXIMO, CODIMOVEL, BAIRRO[]…, buscar=Buscar` | A small JS redirect to `listagem-de-imoveis.php?pagina=1`. The filters are stored **in the PHP session**. |
| Results page | `GET /listagem-de-imoveis.php?pagina=N` (same `PHPSESSID`) | 8 cards per page, a "Mostrando X a Y de TOTAL" counter and Próximo/Último links |
| Listing detail | `GET /detalhes-imovel.php?imovel={code}&finalidade={1,2}` | Full detail page (stateless) |
| Print sheet | `GET /imprimir.php?imovel=..&finalidade=..&acao=imprimir` | Broken: shows "R$0,00 / Valor sob consulta". Not used. |

`finalidade` / `FINALIDADEIMOVEL` takes `1` for Aluguel (rent) and `2` for Venda (sale).

### Search quirks found

- An **empty `TIPOIMO` returns 0 results.** The browser always sends the first type in the
  dropdown.
- `TIPOIMO=0` works as an "any type" search, but it returns **fewer** listings than
  the sum of the per-type searches (on 2026-11-24: 199 vs 225 for sale and 29 vs 32 for rent). A
  complete crawl therefore runs type 0 **and** every type, then removes duplicates by
  `(code, finalidade)`.
- Type IDs that are not in the dropdown always return 0 (I probed IDs 0–30).
- Searches depend on session state, so each search needs its own cookie jar, which also
  makes the searches safe to run in parallel. Detail pages need no session.
- `CODIMOVEL` is ignored by the server. Use the detail URL instead.
- The `VALORMINIMO`/`VALORMAXIMO` filters behave inconsistently. The crawler doesn't use them.
- The "Mostrando X a Y" counter is wrong on the last page (for example "8 a 119 de 119"). The
  client follows the "Próximo" link and stops on an empty page or a repeated page.
- An unknown code, or a code with the wrong `finalidade`, still returns **HTTP 200** with an
  empty template (`".$CODIMOVEL."` placeholders). The parser treats a missing
  `Código: N` header as "not found".

## Data available per listing

**Result card** (`div.thumbnails.carrossel_style`):
- detail link (code and finalidade), thumbnail, property type (`.bairro_carrossel`), price
  (`.valor_imovel`)
- Suítes, Quartos, Banhos and Vagas (`.div_options`; `--` means not informed)
- neighbourhood (`.text-localizacao`)

**Detail page**:
- `span.titulo_h1`: "Código: N"
- `h1.titulo_h1`: a generated sentence with type, area (m²), purpose, neighbourhood, city and
  price. It comes in two formats:
  - `Apartamento residencial de 196 m² à venda no Funcionários, em Belo Horizonte no valor de R$ …`
  - `Casa Comercial para aluguel, 4 vagas, Lourdes - Belo Horizonte/MG no valor de R$ …`
- Gallery `.imagem_galeria_detalhes a[href]`: the full-size photo URLs in display order
- `.item_info` chips: amenities ("Piscina", "1 Varanda" …), `Condomínio R$: X`,
  `IPTU: R$ X`, and the price
- Description: the free-text block under "Descrição do imóvel" (a legal disclaimer
  paragraph is stripped)
- The contact form `textarea[name=MENSAGEM]` is pre-filled with a summary: type, purpose,
  bedrooms, price and neighbourhood

The site doesn't publish a street address, coordinates, broker, or created/updated dates.
The map on every page shows the agency's office.

### Price caveat

Prices are copied **exactly as the site shows them**. Some sale listings appear to be
entered in thousands (for example, 196 m² in Funcionários "à venda" for "R$ 2.450,00").
The scraper keeps `price_text` next to the parsed `price`, so you can apply your own
rules later.
