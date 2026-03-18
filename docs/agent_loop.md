# Pętla Agenta

Ten dokument opisuje pełną pętlę agenta na dwóch poziomach:

- wysokopoziomowo, jako model działania systemu,
- konkretnie, z odniesieniem do implementacji w `4th-devs/01_05_agent`.

## Wysokopoziomowa pętla agenta

### 1. Wejście do systemu

1. Klient wysyła request do endpointu chat.
2. Request przechodzi przez middleware:
   - request ID,
   - secure headers,
   - CORS,
   - body limit,
   - timeout,
   - auth,
   - rate limit.
3. Warstwa HTTP waliduje payload i pobiera runtime.

### 2. Przygotowanie uruchomienia

1. System rozwiązuje konfigurację uruchomienia:
   - template agenta z markdowna,
   - override'y z requestu,
   - model,
   - instructions,
   - tools.
2. System wczytuje sesję albo tworzy nową.
3. System znajduje lub tworzy root agenta sesji.
4. System przygotowuje agenta do kolejnego uruchomienia.
5. Nowy input użytkownika zostaje zapisany jako item.

### 3. Start pętli runtime

1. Runtime startuje agenta.
2. Agent przechodzi do stanu `running`.
3. Emitowane jest `agent.started`.
4. Jeśli agent już jest w stanie `waiting`, runtime nie startuje nowej pracy, tylko zwraca stan oczekiwania.

### 4. Jedna iteracja pętli

Każda iteracja reprezentuje jedną turę agenta.

1. Emitowane jest `turn.started`.
2. Runtime odbudowuje kontekst wejściowy dla modelu:
   - pobiera historię itemów,
   - estymuje rozmiar kontekstu,
   - wykonuje pruning,
   - opcjonalnie generuje summary starszej historii,
   - mapuje itemy do wspólnego formatu providera.
3. Provider dostaje:
   - model,
   - instructions,
   - input,
   - tools,
   - ustawienia generacji.
4. Model zwraca output:
   - tekst,
   - function calls,
   - reasoning,
   - usage.
5. Runtime zapisuje output modelu jako itemy.
6. Emitowane jest `generation.completed`.

### 5. Obsługa function calli

Po odpowiedzi modelu runtime analizuje wszystkie function calle.

Możliwe ścieżki:

- tool synchroniczny:
  - wykonanie od razu,
  - zapis `function_call_output`,
  - eventy `tool.called` oraz `tool.completed` albo `tool.failed`.
- tool MCP:
  - wykonanie przez manager MCP,
  - zapis wyniku jak zwykłego toola.
- tool typu `human`:
  - brak natychmiastowego wykonania,
  - wpis do `waitingFor`,
  - oczekiwanie na zewnętrzne `deliver`.
- tool typu `agent`:
  - utworzenie child agenta,
  - przekazanie mu taska,
  - uruchomienie jego własnej pętli.
- tool zewnętrzny / deferred:
  - brak wykonania lokalnego,
  - wpis do `waitingFor`.

### 6. Decyzja po turze

Po obsłudze tooli runtime podejmuje decyzję:

- jeśli model nie wymaga dalszych kroków, agent kończy pracę,
- jeśli są nowe wyniki i agent może kontynuować, zaczyna następną turę,
- jeśli potrzebne są dane z zewnątrz, agent przechodzi do `waiting`.

Na końcu każdej zakończonej tury:

- akumulowane jest usage,
- zwiększany jest `turnCount`,
- emitowane jest `turn.completed`.

### 7. Przejście do `waiting`

Jeśli agent potrzebuje wyniku spoza bieżącej pętli:

1. zapisuje listę `waitingFor`,
2. przechodzi do stanu `waiting`,
3. emituje `agent.waiting`,
4. API zwraca status oczekiwania zamiast finalnej odpowiedzi.

### 8. Resume po `deliver`

Gdy zewnętrzny system albo użytkownik dostarcza wynik:

1. runtime dopisuje `function_call_output`,
2. usuwa odpowiedni wpis z `waitingFor`,
3. emituje `agent.resumed`,
4. jeśli agent nadal czeka na inne wyniki, pozostaje w `waiting`,
5. jeśli wszystkie brakujące wyniki zostały dostarczone, agent wraca do `running` i kontynuuje pętlę od kolejnej tury.

### 9. Delegacja i child agenci

Delegacja jest częścią tej samej pętli, a nie osobnym subsystemem.

1. Parent agent wywołuje `delegate`.
2. Runtime tworzy child agenta w tej samej sesji.
3. Child dostaje task jako wiadomość użytkownika.
4. Child uruchamia własną pętlę.
5. Jeśli child kończy się synchronicznie, jego wynik wraca do parenta jako `function_call_output`.
6. Jeśli child przechodzi do `waiting`, parent również przechodzi w stan oczekiwania.
7. Po zakończeniu childa wynik może zostać automatycznie propagowany do parenta.

### 10. Zakończenie pracy

Pętla kończy się jednym z trzech stanów:

- `completed`,
- `failed`,
- `cancelled`.

W skrócie cały cykl wygląda tak:

`prepare context -> call model -> store output -> execute tools -> continue albo wait -> resume -> finish`

## Pętla agenta w `4th-devs/01_05_agent`

Poniżej ta sama pętla, ale z mapowaniem do konkretnych plików i funkcji.

### Wejście do pętli

1. Request wpada do endpointu chat w [chat.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.ts#L21).
2. Endpoint woła `prepareChat(...)`, a potem `executePreparedChat(...)` albo `streamPreparedChat(...)` w [chat.service.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.service.ts#L31).
3. `prepareChat(...)` deleguje do `setupChatTurn(...)` w [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L112).

### Co robi `setupChatTurn(...)`

1. Rozwiązuje konfigurację agenta: template z workspace, request overrides, model, instructions, tools w [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L29).
2. Merge’uje tools z requestu i tools z runtime registry w [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L39).
3. Wczytuje sesję albo tworzy nową w [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L69).
4. Szuka lub tworzy root agenta dla sesji w [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L75) i [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L85).
5. Resetuje agenta do kolejnego uruchomienia przez `prepareAgentForNextTurn(...)` w [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L124).
6. Zapisuje nowy input usera jako itemy w [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts#L137).

### Właściwa pętla runnera

1. Startuje w `runAgent(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L712).
2. Jeśli agent jest `pending`, przechodzi do `running` i emituje `agent.started` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L739).
3. Jeśli agent jest już `waiting`, runner od razu zwraca stan oczekiwania w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L762).
4. Potem leci główna pętla `while (agent.status === 'running' && agent.turnCount < maxTurns)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L768).

### Jedna tura

1. Emisja `turn.started` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L776).
2. Wywołanie `executeTurn(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L782).

### Co robi `executeTurn(...)`

1. Woła `prepareTurnInput(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L489).
2. `prepareTurnInput(...)`:
   - rozwiązuje providera z model stringa,
   - pobiera itemy z repo,
   - sprawdza pruning,
   - opcjonalnie generuje summary starych itemów,
   - mapuje itemy do formatu providera
   w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L153).
3. Potem provider dostaje `generate(...)` z modelem, instructions, inputem i tools w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L619).
4. Po odpowiedzi emitowane jest `generation.completed` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L630).
5. Następnie `handleTurnResponse(...)` analizuje output modelu w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L226).

### Co robi `handleTurnResponse(...)`

1. Zapisuje output modelu jako itemy przez `storeProviderOutput(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L101) i [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L236).
2. Jeśli nie ma function calli, kończy agenta przez `completeAgent(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L242).
3. Jeśli są function calle, iteruje po nich i dla każdego wybiera ścieżkę:
   - MCP tool call w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L259),
   - external/deferred tool w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L295),
   - `delegate` / tool typu `agent` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L306),
   - `ask_user` / tool typu `human` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L329),
   - sync tools w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L343).
4. Specjalny case `send_message` jest interceptowany osobno w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L345) i realizowany przez `handleSendMessage(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L481).
5. Delegacja tworzy child agenta i odpala jego `runAgent(...)` rekurencyjnie w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L403).
6. Jeśli child kończy się synchronicznie, parent dostaje `function_call_output`; jeśli child przejdzie w `waiting`, parent też czeka w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L437).

### Powrót do głównej pętli

1. Po `executeTurn(...)` runner:
   - obsługuje błąd i ustawia `failed` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L784),
   - akumuluje usage i zwiększa `turnCount` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L796),
   - emituje `turn.completed` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L804).
2. Jeśli tura zwróciła `waiting`, agent przechodzi do `waiting`, zapisuje `waitingFor` i runner zwraca kontrolę do API w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L811).
3. Jeśli tura zwróciła `continue: true`, pętla robi następną iterację.
4. Jeśli nie ma już dalszej pracy, emitowane jest `agent.completed` i runner kończy w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L832).

### Resume po `waiting`

1. `POST /agents/:agentId/deliver` trafia do [chat.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.ts#L78).
2. Warstwa service woła `deliverResult(...)` w [chat.service.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.service.ts#L71).
3. Runner dopisuje `function_call_output`, usuwa element z `waitingFor`, emituje `agent.resumed` i jeśli wszystko dostarczono, znowu woła `runAgent(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L868).
4. Jeśli ukończony agent ma parenta i `sourceCallId`, wynik dziecka jest automatycznie propagowany do parenta przez kolejne `deliverResult(...)` w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L921).

### Streaming

1. Ścieżka stream zaczyna się w [chat.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.ts#L43).
2. Service woła `runAgentStream(...)` przez [chat.service.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.service.ts#L94).
3. Stream ma tę samą logikę pętli, tylko eventy providera są wypychane na bieżąco w [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts#L951).

## Skrót mentalny

Jeśli chcesz szybko czytać przykład, najpraktyczniejsza kolejność jest taka:

1. [chat.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.ts)
2. [chat.service.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.service.ts)
3. [chat.turn.ts](/home/netherman/code/4th-devs/01_05_agent/src/routes/chat.turn.ts)
4. [runner.ts](/home/netherman/code/4th-devs/01_05_agent/src/runtime/runner.ts)
5. [agent.ts](/home/netherman/code/4th-devs/01_05_agent/src/domain/agent.ts)
6. [workspace/loader.ts](/home/netherman/code/4th-devs/01_05_agent/src/workspace/loader.ts)
7. [events/types.ts](/home/netherman/code/4th-devs/01_05_agent/src/events/types.ts)

To daje pełny obraz:

`HTTP -> prepare turn -> run loop -> execute turn -> handle tools -> wait/resume -> complete`
