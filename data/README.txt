AEQUITAS RESEARCH INTELLIGENCE ASSIGNMENT - DATA PACK

Purpose
-------
This dataset is a fictionalised research-information repository created for a product-development assessment. It is designed to resemble the mix of company disclosures, news, sector updates and low-value information that an equity research team may encounter.

Important
---------
- All company names, tickers, events and figures in this pack are fictional.
- The pack is self-contained and is NOT intended to represent any real listed company or investment view.
- Some imperfections are intentional: duplicate/near-duplicate stories, incomplete metadata, aliases, routine/noisy items and follow-up updates.
- Candidates may clean, restructure, enrich or transform the data as they consider appropriate.

Files
-----
1. research_feed.csv       - Main repository (250 records)
2. company_master.csv      - Company metadata and aliases
3. watchlist.csv           - Sample research watchlist
4. research_repository.xlsx- Same data in a formatted workbook + data dictionary
5. raw_documents/          - Source-context text file for every feed record

Suggested starting point
------------------------
Use research_feed.csv as the primary input. The source_path field links each row to a corresponding file in raw_documents/ for additional context.
