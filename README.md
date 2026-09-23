# mail-labeler

Mini self-study basic gcp functionality project.

I wanted to set up a simple pipeline (without adding billing to GCP!) that would automatically label every new email that comes in to my gmail with one of my predefined labels.

Requirements:
- Gmail account
- GCP environment set up

Soft requirements:
- Access to some kind of LLM (or *something else* that can label emails based text/content for your own specific labels; can be a black box). I am using deepseek API in this project.
- *something else* can be a ML classifying model trained on embedded email content (using some kind of embedding model)
- or hyped Jev model (TypeSafe AI) 

### Setting up GCP project:

1. GCP project (and enable APIs)
2. Pub/Sub Topic
3. Pub/Sub Subscription
4. OAuth and watch function 
5. Cloud Function - label logic