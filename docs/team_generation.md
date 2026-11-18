# Team generation

The backend generates teams with the Teamable algorithms API (repository
[`algorithms`](https://github.com/Teamprojekt-MSI-BIT-SS26/algorithms)):
`POST /api/v1/courses/{id}/generate_teams/` sends the students of the course to the API and saves the
returned teams as a `TeamSet`.

The full documentation (interface, parameters, error codes, data mapping, result validation and tests)
is in the project documentation:

- [Integration and interface](https://teamprojekt-msi-bit-ss26.github.io/documentation/umsetzung/Backend-Integration/INTEGRATION_EN/)
  ([Deutsch](https://teamprojekt-msi-bit-ss26.github.io/documentation/umsetzung/Backend-Integration/INTEGRATION/))
- [Local backend tests](https://teamprojekt-msi-bit-ss26.github.io/documentation/umsetzung/Backend-Integration/TESTS_EN/)
  ([Deutsch](https://teamprojekt-msi-bit-ss26.github.io/documentation/umsetzung/Backend-Integration/TESTS/))

## Quick start

1. Start the algorithms API on port 8001 (see `algorithms/api/README.md` in the algorithms repository).
2. Set the plain API key in `.env` (see `sample.env`):
    ```
    TEAM_GENERATION_API_URL=http://localhost:8001/api/generate/teams/
    TEAM_GENERATION_API_KEY=<key>
    ```
3. Run the tests in `src`:
    ```bash
    python manage.py test app.tests -v 2
    ```
   The integration tests are skipped if the algorithms API is not running.

The code is in `src/app/services/team_generation.py`, the request parameters in
`src/app/serializers/team_generation.py` and the tests in `src/app/tests/`.
