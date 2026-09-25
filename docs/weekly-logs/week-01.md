# Week 01 — Project Formulation

## Goal

Define a practical AI cooking assistant for Vietnamese students living in Taiwan.

## Problem

Students may have access to locally available vegetables, meat and packaged ingredients but lack cooking experience or do not know which Vietnamese dishes can be made from them.

## Initial idea

1. Build a structured Vietnamese recipe knowledge base from cooking content.
2. Build a Taiwan-local ingredient image dataset with multilingual labels.
3. Recognize ingredients using computer vision.
4. Retrieve recipes matching the available ingredients.
5. Rank recipes by ingredient availability, cooking time, cost and difficulty.
6. Add a RAG-based cooking assistant after retrieval is reliable.

## Key architecture decision

Do **not** treat approximately 1,000 recipes as sufficient reason to train a new language model from scratch.

Use the recipes primarily as a retrieval knowledge base. Train/fine-tune the vision component when enough labeled images have been collected.

## Week 01 output

- repository initialized;
- project scope defined;
- recipe JSON schema created;
- first 20 Taiwan ingredient classes defined;
- sample recipe records created;
- baseline recommendation/retrieval structure started.

## Next step

Build and validate the first 100-recipe dataset before scaling collection.
