# API Examples

## Failure probability

```http
POST /api/v1/failure-probability/analyze
Authorization: Bearer <token>
Content-Type: application/json
```

The request contains material, stack-up, current parameters, recommended ranges,
nugget prediction, and minimum nugget target.

The response contains ordered failure modes, probabilities, confidence,
contributors, tests, and corrective actions.
