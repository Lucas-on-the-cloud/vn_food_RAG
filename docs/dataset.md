# Dataset Strategy

## 1. Recipe knowledge base

Target scale: 1,000 Vietnamese student-friendly recipes.

Start with 100 recipes for the MVP.

Each item should be traceable to its source and converted into the shared recipe schema.

### Important fields

- recipe ID
- Vietnamese dish name
- source URL/platform
- canonical ingredient IDs
- original ingredient names
- quantities
- cooking steps
- cooking time
- difficulty
- estimated cost in TWD
- required equipment
- tags

## 2. Taiwan ingredient dataset

The first version contains 20 classes defined in:

`dataset/ingredients/ingredient_mapping.csv`

The taxonomy uses a canonical English ID while preserving Vietnamese and Traditional Chinese labels.

### Collection recommendations

For each class, collect diverse images across:

- supermarkets;
- traditional markets;
- dorm/apartment kitchens;
- packaged and unpackaged ingredients;
- different lighting;
- different backgrounds;
- different camera angles.

Avoid collecting hundreds of near-identical frames from the same video because they provide less useful diversity.

## 3. Suggested first image target

For an MVP classification experiment:

- 20 classes
- approximately 100-200 useful images per class where feasible
- train/validation/test splits without near-duplicate leakage

This gives roughly 2,000-4,000 images.

## 4. Data governance

Store large/raw datasets outside normal Git history.

Git should contain:

- schemas;
- metadata;
- small samples;
- annotation definitions;
- reproducible scripts.

Do not commit:

- large raw videos;
- private data;
- API keys;
- model checkpoints;
- large vector indexes.

## 5. Future annotation

When upgrading from single-ingredient classification to pantry-image object detection, annotate bounding boxes and maintain train/validation/test splits at the source-image level.
