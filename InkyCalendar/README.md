# InkyCalendar Backbone

This folder contains the first-pass app backbone for pairing a mobile app with the Raspberry Pi calendar service.

## Connection flow

1. App calls `POST /connection/start` to check if the Pi can be reached.
2. If `prompt_continue` is `true`, show a popup asking if the user wants to continue while services are already active.
3. After confirmation, app calls `POST /connection/authorize` with `{"continue_when_active": true}`.
4. Pi returns a **random 6-digit authorization code** and displays this code on the Inky display.
5. User enters the displayed code in the app.
6. App calls `POST /connection/complete` with `{"authorization_code": "123456"}` to complete the connection.

## API payload examples

- Start connection:
  - Request: `{}`
  - Response: `{"can_connect": true, "services_active": true, "prompt_continue": true, "prompt_message": "..."}`

- Create code:
  - Request: `{"continue_when_active": true}`
  - Response: `{"display_authorization_code": "104928", "code_length": 6}`

- Complete connection:
  - Request: `{"authorization_code": "104928"}`
  - Response: `{"connected": true}`
