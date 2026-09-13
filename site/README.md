# The site

The public face of Nowplay: Radio World, served by GitHub Pages from this
folder, at

    https://meoscar.github.io/internetradiolist/
    https://meoscar.github.io/internetradiolist/privacy.html
    https://meoscar.github.io/internetradiolist/zh-TW/
    https://meoscar.github.io/internetradiolist/for-stations/<station>.html

Only this folder is published; the workflow uploads `site/` and nothing
else, so the catalogue's files are not served as a website even though
they are in the same repository. The pipeline that builds the catalogue
stays here too, because Actions minutes are free on a public repository
and the pipeline runs every quarter of an hour.

- `index.html`, `zh-TW/`: what the app is, in English and Traditional Chinese.
- `privacy.html`, `zh-TW/privacy.html`: the privacy policy Play asks for.
- `store/`: the listing's pictures, drawn by the app repository's generator
  and copied here; the `r1` to `r6` ones are photographs of the phone.
- `robots.txt`, `sitemap.xml`: the two index pages and the privacy policy
  are for search engines; `for-stations/` is kept out, and each station
  page also says `noindex` itself, because the catalogue is not a directory
  to be found through Google.
- `station_pages.py`: at publish time, one page per station into
  `for-stations/`, from this repository's catalogue. A page carries the
  station's own name, logo, genre and site and a link to the app; there is
  no index and no list.

`.github/workflows/pages.yml` publishes on a push that touches this folder,
every Monday so the station pages follow the catalogue, and on demand.
