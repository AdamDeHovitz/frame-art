# Stillroom

Find art for a Samsung Frame TV. Stillroom searches open-access collections, lets you choose a crop and preview a frame finish, then downloads a TV-ready image or sends it to your TV over your home network.

You can also save favorites, send a seasonal collection as a slideshow, and view or delete images in the TV's **My Photos** library.

## Get started

You need Python 3. Direct TV transfer also needs Git to install the optional TV package. Art browsing and downloads work without that package.

### macOS or Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-tv.txt
python3 server.py
```

### Windows

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-tv.txt
.venv\Scripts\python.exe server.py
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** on the same computer. Leave the terminal running while you use Stillroom. Press **Ctrl+C** to stop it.

If you only want to browse and download art, skip the installation commands and run `python3 server.py` (or `py server.py` on Windows).

## Find and prepare art

1. Browse the seasonal sets or search for an artist or subject. The gallery searches all supported collections by default; **Filter by collection** narrows the results.
2. Select a work. Choose landscape or portrait, position the crop, and use **Trim artwork edges** if the image includes paper or a photographed frame.
3. Pick a **Preview frame** finish if you like. It only changes the on-screen preview; it is never added to the image sent to the TV.
4. Choose **Download TV-ready artwork**, or pair your TV and choose **Send to Frame TV**. Landscape images export at 3840 × 2160; portrait images export at 2160 × 3840.

## Enlarge the frame preview

After selecting artwork, choose **Enlarge preview** beside the preview heading. The artwork fills the available space, with the same frame, orientation, and crop controls alongside it (below it on a phone). Changes carry back to your composition. Choose **Close** or press **Escape** to return. The browser stays in its normal window so navigation and device controls remain available.

## Use an image from your computer or phone

Choose **Upload your own image** above the frame preview and select a JPEG or PNG up to 30 MB. The image opens in the existing preview: adjust landscape or portrait orientation, position the crop, and choose **Download TV-ready artwork** or **Send to Frame TV**. Transparent areas in PNG images export on white.

Your images appear under **Your uploaded images** for the current browser tab. You can return to them, adjust their crops, or send multiple imported images as a slideshow. They stay in browser memory and are cleared when the page is refreshed or closed; they are not added to saved favorites. The original file stays on your device. Only sending to the TV transfers the exported JPEG to the local server. Images already uploaded to the TV remain in its My Photos library after you close Stillroom.

## Pair your Frame TV

Your TV and computer must be on the same home network. Turn on the TV before pairing.

1. On the TV remote, open **Settings → All Settings → Connection → Network → Network Status → IP Settings**.
2. Find the number labeled **IP Address**. It usually looks like `192.168.1.50`. On older Samsung TVs, try **Settings → General → Network → Network Status → IP Settings**.
3. Enter that number in Stillroom's **Connect your Frame TV** box, without `http://` or a port, then select **Pair TV**.
4. Accept the **Stillroom** connection request that appears on your TV.
5. Select a work and choose **Send to Frame TV**.

The same instructions are available from **Find your TV's IP** beside the pairing box in the app. Samsung's [network status guide](https://www.samsung.com/ca/support/tv-audio-video/verify-network-status-on-your-samsung-tv/) shows the menu path; labels can vary by model and region.

### If pairing or transfer fails

- Check that the address is the TV's current IP address. It can change after a router restart.
- Keep the TV awake and both devices on the same network. Guest networks can block local device connections.
- Confirm you installed `requirements-tv.txt` and restarted the server. Stillroom will say when the TV package is missing.
- If direct transfer is unavailable on your TV or firmware, download the JPEG and add it through Samsung SmartThings or USB. Samsung's [Frame artwork guide](https://www.samsung.com/us/support/answer/ANS10005224/) covers those methods.

Direct transfer uses a community-maintained Art Mode connection over the local network. It does not use SmartThings. Stillroom checks whether the TV reports Art Mode support, but upload behavior can vary by firmware.

## Collections, slideshows, and TV photos

- Choose a seasonal set, or tap **♡** on individual works and open **Your saved works**.
- Select an interval and choose **Send all to TV & start slideshow**. Stillroom uploads each work, displays the first, and changes images at the chosen interval. Keep this computer and server running; restarting the server stops the slideshow. **Stop slideshow** leaves uploaded images in My Photos.
- **My Photos on TV** shows images currently stored on the TV, including ones added outside Stillroom. Refresh the list to see recent changes. Select images and choose **Delete selected from TV** to remove them after a confirmation.

The TV may add a mat or scale images according to its Art Mode settings. The preview frame finish does not control the physical bezel or the TV's mat setting.

## Privacy and publishing

Stillroom runs at `127.0.0.1:8000` on your computer. It stores the TV address and pairing tokens locally in `work/tv/` with owner-only file permissions. Artwork JPEGs are generated in the browser and sent to the local server only for TV transfer. Favorites and crop choices stay in your browser's local storage.

The project's `.gitignore` excludes `work/`, `.venv/`, generated files, and local exports. Publish the Git-tracked source files; do not upload the entire folder through a website or force-add ignored files. If a token was ever committed to another repository, remove it from that repository's history and re-pair the TV before publishing.

## Art sources and rights

- [Cleveland Museum of Art Open Access](https://www.clevelandart.org/open-access): records marked CC0, with web and print images.
- [The Met Open Access](https://www.metmuseum.org/about-the-met/policies-and-documents/open-access): public-domain works with images.
- [Rijksmuseum Data Services](https://data.rijksmuseum.nl/tutorials/search/): public-domain or CC0 paintings with images from its keyless search and IIIF APIs.
- [Wikimedia Commons reuse guide](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia): files marked public domain or CC0.

Stillroom filters for flat art such as paintings, drawings, prints, and posters, and excludes photography and three-dimensional objects. Each result links to its source record so you can check the image and rights before reuse. The app uses the community-maintained [Samsung TV WebSocket API library](https://github.com/NickWaterton/samsung-tv-ws-api) for optional local TV transfer.

## Project files

- `index.html` and `styles.css` — app layout and appearance
- `app.js` — browsing, preview, crop, favorites, and export
- `collections.json` — curated seasonal sets
- `server.py` — local server and museum image relay
- `tv_transfer.py` and `requirements-tv.txt` — optional TV pairing and transfer
