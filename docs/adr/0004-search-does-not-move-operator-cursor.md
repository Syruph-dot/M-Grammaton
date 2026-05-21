# Search report creation does not move the Operator cursor

Operator search may create `web_page` artifacts and a `search_report`, but it does not automatically move the Operator cursor to the report. The cursor stays on the triggering node to avoid losing the main reading/navigation thread; generated reports are automatically added to that Operator's stash as the memory anchor, while individual web pages are not auto-stashed.
