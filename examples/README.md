# Examples

Request/response samples you can replay with `curl` against a running stack
(`docker compose up -d --build`). Replace the `<...>` placeholders with ids
from `POST /api/v1/accounts`.

| File                              | Purpose                                              |
|-----------------------------------|------------------------------------------------------|
| `create_account.json`             | Body for `POST /api/v1/accounts`                     |
| `journal_entry_deposit.json`      | Balanced funding entry (debit asset, credit customer)|
| `journal_entry_unbalanced.json`   | Rejected with `422 UNBALANCED_JOURNAL`               |
| `transfer.json`                   | Body for `POST /api/v1/transfers`                    |
| `payment_instruction.json`        | ISO 20022-inspired body for `POST /api/v1/payments/instructions` |
| `requests.http`                   | VS Code REST Client / IntelliJ HTTP file with the full flow |

```bash
curl -s -X POST localhost:8000/api/v1/accounts -H 'Content-Type: application/json' \
  -d @examples/create_account.json
```
