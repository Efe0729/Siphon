# The app

Siphon has four tabs. This page says what each one does; the README says how to
install it and how to add a site.

## Browse

The site picker lists the sites you added, in the order you arranged them in
Settings. Choosing one loads its sections and categories; the grid shows
thumbnails, titles and running times, with paging and the site's own search.

Select videos one by one, take the whole page, or scan every page of the
current listing and take all of it. Selected videos go to the queue or start
downloading straight away. Preview opens a video on its own site, in your
browser, without downloading anything.

With no sites added, Browse shows a short page with a button that takes you to
the place where sites are added.

## Download

A queue with positions: move a row up or down, pause, resume, retry, cancel,
or clear what has finished. Each row shows its state, percentage, speed, size
and, if something went wrong, the reason.

- Paste a link, or several at once.
- Import a list from a text, CSV or JSON file; export the current list the
  same way.
- A video already in the history is spotted before it downloads again, by its
  address and by its file name. You can still force it.
- An estimate of the time left for everything queued, based on your speed
  limit.
- Rows waiting in the queue have their real titles read from their pages, so a
  pasted link does not sit there as a number.

## Upload

Sends finished files to Google Drive through rclone.

Pick a folder or files; every file becomes its own row, and each upload asks
where it should go. Uploads can run several at a time, be paused and resumed,
and be reordered. Files already present in the destination are skipped rather
than uploaded twice. The queue survives closing the app.

Connecting your own Google key is worth doing: the shared key rclone ships
with is rate-limited and causes repeated restarts on large files.

## Settings

Download folder, speed limit, how many downloads at once, connections per
video (also per site), video quality, file naming, scheduling, minimum free
disk space, automatic retries and the completion notification.

Below those: your own sites (add, order, turn off, remove, teach from a saved
page), proxy settings, Cloudflare details, where the saved queue lives, theme,
language, and the app's version.

## Command line

```
siphon-app --nogui --url "https://example.com/videos/1/" -o ./download
```
