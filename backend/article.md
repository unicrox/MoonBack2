I have been building a workflow that makes AI answers traceable, inspectable, and connected to evidence.

The idea is simple:
AI should not only give an answer.
It should also show how it got there.

In this project, each investigation starts with a question. The system can then break that question into smaller questions, search for evidence, store the raw results, and generate a conclusion.

Every step is saved as a point in the investigation.
- There is a root point for the original question.
- There are child points for smaller questions.
- There are evidence points for data collected from external sources.

Each point can have its own reason, raw data, and conclusion.

This creates a visible chain:
question -> investigation steps -> evidence -> conclusion

I like this structure because it makes AI answers easier to inspect.

If the final answer looks wrong, I can trace where the problem happened:
- Was the question split badly?
- Was the wrong data searched?
- Was the evidence incomplete?
- Was the conclusion too weak?

For business AI, a good answer is not enough. The answer needs to be connected to evidence.

That is what I am exploring with this project: AI systems that do not just answer questions, but build evidence-backed investigations.
