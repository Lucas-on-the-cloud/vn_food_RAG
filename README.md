# VN Food RAG 🇻🇳🍳🇹🇼

A multimodal AI project for Vietnamese students in Taiwan: recognize available ingredients, retrieve suitable Vietnamese recipes, and recommend affordable, beginner-friendly meals.

## Motivation

Many students living abroad have limited cooking experience and often face a simple question:

> "I have these ingredients. What Vietnamese dishes can I cook?"

This project turns Vietnamese short-form cooking content into a structured recipe knowledge base and combines it with a Taiwan ingredient dataset.

The system is designed around **retrieval and recommendation**, not blindly fine-tuning a language model on 1,000 recipes.

## Core Idea

```text
Vietnamese cooking videos
        |
        v
Speech / text extraction
        |
        v
Structured recipe dataset
        |
        +--------------------+
                             |
Taiwan ingredient images    |
        |                    |
        v                    |
Ingredient recognition      |
        |                    |
        +---------> Recipe retrieval
                             |
                             v
                    Ranking / filtering
                             |
                             v
                    RAG cooking assistant
```

## Main Components

### 1. Vietnamese Recipe Dataset

Target: approximately **1,000 student-friendly Vietnamese recipes**.

Each recipe is normalized into structured fields such as:

- dish name
- ingredients
- quantities
- cooking steps
- cooking time
- difficulty
- equipment
- estimated cost
- source metadata

### 2. Taiwan Ingredient Dataset

A custom dataset of ingredients commonly available to students in Taiwan.

Initial MVP target:

- 20-30 ingredient classes
- Vietnamese / Traditional Chinese / English labels
- locally collected images
- supermarket and traditional market packaging variations

Example classes:

- pork belly / 五花肉 / thịt ba chỉ
- egg / 雞蛋 / trứng
- tofu / 豆腐 / đậu phụ
- water spinach / 空心菜 / rau muống
- bok choy / 青江菜 / cải thìa

### 3. Ingredient Recognition

Initial baseline:

```text
Image -> classifier -> ingredient label
```

Later:

```text
Pantry / refrigerator image
        |
        v
Object detector
        |
        v
Multiple ingredient labels
```

### 4. Recipe Retrieval

Recognized ingredients are matched against the recipe knowledge base.

Example:

```text
User ingredients:
- egg
- pork belly
- tofu

        |
        v

Retrieve candidate recipes

        |
        v

Rank by:
- ingredient coverage
- missing ingredients
- cost
- cooking time
- difficulty
```

### 5. RAG Cooking Assistant

The language model receives retrieved recipes as context instead of inventing recipes from scratch.

Example query:

> I have pork belly, eggs and tofu. My budget is NT$100 and I only have 30 minutes.

The assistant retrieves relevant recipes and explains the best matching options.

## MVP Scope

The first usable version will contain:

- [ ] 100 structured Vietnamese recipes
- [ ] 20 Taiwan ingredient classes
- [ ] baseline ingredient image classifier
- [ ] recipe retrieval
- [ ] recommendation scoring
- [ ] simple web interface

After the MVP:

- [ ] scale to 500 recipes
- [ ] scale to 1,000 recipes
- [ ] expand to 50-100 ingredient classes
- [ ] upgrade classification to object detection
- [ ] add vector search
- [ ] add RAG cooking assistant
- [ ] add cost-aware recommendation
- [ ] add user preference learning

## Proposed Recommendation Score

A first baseline can use:

```text
score =
    0.50 * ingredient_match
  + 0.15 * cooking_time_score
  + 0.15 * cost_score
  + 0.10 * difficulty_score
  + 0.10 * user_preference_score
```

The weighting will later be evaluated experimentally.

## Repository Structure

```text
vn_food_RAG/
├── configs/
├── data/
│   ├── raw/
│   ├── processed/
│   └── samples/
├── dataset/
│   ├── recipes/
│   └── ingredients/
├── docs/
├── experiments/
├── notebooks/
├── src/
│   ├── collection/
│   ├── transcription/
│   ├── recipe_extraction/
│   ├── vision/
│   ├── retrieval/
│   ├── recommendation/
│   └── utils/
├── tests/
├── .gitignore
├── requirements.txt
└── README.md
```

## Development Phases

### Phase 1 — Recipe Knowledge Base
1. Define recipe schema.
2. Collect an initial set of recipes.
3. Extract transcript / text.
4. Convert unstructured content to structured JSON.
5. Normalize ingredient names.

### Phase 2 — Taiwan Ingredient Dataset
1. Define ingredient taxonomy.
2. Create multilingual labels.
3. Collect local images.
4. Annotate and split the dataset.

### Phase 3 — Ingredient Recognition
1. Train a classification baseline.
2. Evaluate class accuracy.
3. Upgrade to multi-object detection when enough data is available.

### Phase 4 — Retrieval & Recommendation
1. Ingredient matching baseline.
2. Missing-ingredient calculation.
3. Cost/time/difficulty filters.
4. Embedding/vector retrieval.
5. Ranking experiments.

### Phase 5 — RAG Assistant
1. Retrieve recipes.
2. Inject retrieved evidence into the prompt.
3. Generate beginner-friendly cooking instructions.
4. Evaluate grounding and recommendation quality.

## Data Note

Raw videos, large image datasets, model weights, vector indexes and secrets should **not** be committed directly to Git.

Only schemas, small samples, metadata and reproducible scripts belong in the repository.

## Status

**Stage:** Project initialization / dataset design.

The current priority is building a small, clean MVP before scaling to 1,000 recipes.
