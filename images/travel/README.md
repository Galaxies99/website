# Travel photos

Drop photos here using the naming convention:

```
<countryCode>-<slug>.jpg     e.g. cn-shanghai-bund.jpg
<countryCode>-<slug>.png     e.g. tr-istanbul-bosphorus.jpg
```

The `countryCode` is the lowercase ISO 3166-1 alpha-2 code used in the JS
`TRAVELS` array near the bottom of `index.html`:

```
cn  China
us  USA
gb  UK
at  Austria
tr  Türkiye
no  Norway
dk  Denmark
cz  Czech Republic
hu  Hungary
sg  Singapore
kr  South Korea
jp  Japan
qa  Qatar
```

## Adding / editing a country or photo

Open `index.html`, search for the `TRAVELS` array (look for `// Travels data`)
and edit it. Each country looks like:

```js
{
  code: 'tr', name: 'Türkiye', flag: '🇹🇷', continent: 'Asia',
  cities: ['Istanbul'],
  // Optional. Pick which photo is used as the card cover.
  // Accepts either a full path or just the filename.
  // If omitted, the first photo in `photos` is used.
  cover: 'tr-istanbul-bosphorus.jpg',
  photos: [
    { src: 'images/travel/tr-istanbul-bosphorus.jpg',
      city: 'Istanbul', year: '2024',
      caption: 'Sunset over the Bosphorus.' }
  ]
}
```

Empty `photos: []` is fine — the card will fall back to a styled flag
placeholder until you add images.

Recommended photo size: ~1200–1600 px on the long edge, JPG/WebP for cover
photos. Keep file size under ~400 KB each so the page stays fast.
