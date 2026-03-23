# Plan naprawy obsługi tooli

## Cel

Naprawić obsługę błędów tooli w `manfred` tak, aby agent nie dostawał "gołego" exception/stringa, tylko ustrukturyzowany kontekst pozwalający na autorecovery.

To jest zgodne z wnioskami z:

- `obsidian/aidevs/s01/s01e02-techniki-laczenia-modelu-z-narzedziami-1773132164.md`
- `obsidian/aidevs/s01/s01e05-zarzadzanie-jawnymi-oraz-niejawnymi-limitami-modeli-1773377197.md`
- przykładu `4th-devs/01_02_tool_use`

## Wnioski z lekcji S01

Najważniejsze wzorce z S01, które powinny sterować implementacją:

- tool ma zwracać modelowi jasną informację co się wydarzyło, nie tylko że "coś poszło nie tak";
- walidacja i błędy muszą zawierać wskazówki, co agent powinien zrobić dalej;
- ograniczenia programistyczne są poprawne, ale powinny być komunikowane jako czytelny rezultat toola;
- wyjątek powinien oznaczać błąd nieprzewidziany po stronie systemu, a nie normalny scenariusz walidacyjny.

W praktyce oznacza to: przewidywalne błędy powinny wracać jako `{"ok": false, ...}`, a nie przez `raise`.

## Stan obecny w `manfred`

### 1. Runner już wspiera soft-fail, ale tylko częściowo

W `src/app/runtime/runner.py`:

- `handle_turn_response()` poprawnie zapisuje `is_error` dla wyniku toola;
- ale `_serialize_tool_result_output()` zachowuje pełny payload błędu tylko dla `verify_task`;
- dla wszystkich pozostałych tooli runner ucina wynik do samego `error` stringa.

To jest główna strata kontekstu dla agenta.

### 2. Registry zamienia exception na soft-fail, ale bez struktury

W `src/app/domain/tool.py`:

- `ToolRegistry.execute()` łapie wyjątek i zwraca `{"ok": False, "error": ...}`;
- przez to proces nie wybucha globalnie, ale agent traci `hint`, `details`, `retryable`, `received_args` itp.;
- dodatkowo registry nie rozróżnia błędu przewidywalnego od awarii systemowej.

### 3. Wiele tooli nadal używa `raise` do walidacji wejścia

Dotyczy to m.in.:

- `src/app/agent/tools/wait.py`
- `src/app/agent/tools/calculator.py`
- `src/app/agent/tools/audio/*.py`
- `src/app/agent/tools/images/*.py`
- `src/app/agent/tools/files/common.py`
- `src/app/agent/tools/files/read_file.py`
- `src/app/agent/tools/files/list_files.py`
- `src/app/agent/tools/files/write_file.py`
- `src/app/agent/tools/files/delete_file.py`
- `src/app/agent/tools/ai_devs/verify_task.py`

To są głównie błędy przewidywalne:

- brak wymaganych argumentów,
- zły typ argumentu,
- ścieżka absolutna lub wychodząca poza workspace,
- plik nie istnieje,
- wskazany katalog nie jest plikiem,
- niepoprawny shape `answer` dla `verify_task`.

To nie powinny być exceptiony sterujące normalną logiką toola.

## Docelowy kontrakt odpowiedzi toola

Minimalna, spójna forma:

```json
{
  "ok": false,
  "error": "wait expects a numeric argument: 'time'.",
  "hint": "Podaj pole 'time' jako number >= 0, np. 5.",
  "details": {
    "received": {
      "time": "soon"
    },
    "expected": {
      "time": "number >= 0",
      "next_task": "non-empty string"
    }
  },
  "retryable": true
}
```

Dla sukcesu zostaje prosto:

```json
{
  "ok": true,
  "output": {}
}
```

Założenia:

- `error` ma być krótkim komunikatem diagnostycznym;
- `hint` ma mówić agentowi co zrobić dalej;
- `details` ma dawać kontekst do korekty kolejnego wywołania;
- `retryable` ma odróżniać błąd naprawialny przez agenta od błędu terminalnego;
- przewidywalne błędy walidacyjne i domenowe mają zwracać ten kontrakt bez `raise`.

## Plan implementacji

### Etap 1. Ujednolicić kontrakt błędu

Dodać wspólny sposób budowania odpowiedzi tooli, np. helpery w `src/app/domain/tool.py` albo osobnym module:

- `tool_ok(output)`
- `tool_error(error, hint=None, details=None, retryable=True)`
- opcjonalnie `tool_internal_error(error, details=None)`

Cel:

- usunąć ręczne składanie słowników w każdym toolu;
- wymusić jeden format błędów;
- uprościć testy.

### Etap 2. Przestać ucinać błąd w runnerze

W `src/app/runtime/runner.py` zmienić `_serialize_tool_result_output()` tak, aby:

- dla każdego `ok == false` serializował pełen obiekt błędu;
- usunąć wyjątek/specjalny case dla `verify_task`;
- nie sprowadzać błędu do samego stringa.

To jest najważniejsza zmiana, bo bez niej nawet dobrze napisane toole nadal stracą kontekst zanim odpowiedź wróci do modelu.

### Etap 3. Rozdzielić błędy przewidywalne od awarii systemowych

W `ToolRegistry.execute()` zostawić `try/except`, ale zmienić semantykę:

- jeśli tool zwróci `{"ok": false, ...}`, registry tylko loguje i przekazuje wynik dalej;
- jeśli handler rzuci wyjątek, registry zwraca generyczny błąd systemowy w tym samym kontrakcie, np.:

```json
{
  "ok": false,
  "error": "Tool execution failed.",
  "hint": "Spróbuj innego podejścia albo poinformuj użytkownika o problemie systemowym.",
  "details": {
    "tool": "read_file"
  },
  "retryable": false
}
```

Ważne: exception nadal logujemy jako incident techniczny, ale nie używamy go jako podstawowego mechanizmu komunikacji z agentem.

### Etap 4. Zrefaktoryzować walidację w toolach

Kolejno przepisać toole tak, aby przewidywalne błędy kończyły się `return tool_error(...)`.

Priorytet:

1. `wait`
2. `calculator`
3. `files/*`
4. `verify_task`
5. `audio/*`
6. `images/*`

Dlaczego taka kolejność:

- `wait` i `calculator` są najprostsze i dobre na ustalenie kontraktu;
- `files/*` najczęściej będą potrzebowały autorecovery;
- `verify_task` już częściowo zwraca soft-fail i jest najlepszym kandydatem do ujednolicenia;
- `audio` i `images` mają prostą walidację wejścia i mały zakres zmian.

### Etap 5. Uporządkować helpery filesystemu

W `src/app/agent/tools/files/common.py` obecne helpery `ensure_*` i `resolve_tool_path()` rzucają `ValueError`.

Plan:

- zostawić funkcje strict tylko do użytku wewnętrznego jeśli są potrzebne;
- dodać warstwę "LLM-friendly", która zamiast `raise` zwraca wynik błędu z hintem;
- dla typowych przypadków przygotować konkretne komunikaty:
  - ścieżka absolutna,
  - path traversal,
  - brak pliku,
  - oczekiwano katalogu,
  - oczekiwano pliku,
  - próba nadpisania katalogu.

Toole plikowe powinny też zwracać `details.path` i, gdzie ma to sens, propozycję kolejnego kroku, np. "użyj `list_files` dla katalogu nadrzędnego".

### Etap 6. Dodać hinty domenowe

Największy zysk będzie z hintów, które realnie pomagają agentowi poprawić kolejną próbę.

Przykłady:

- `wait`: "podaj liczbę sekund jako number";
- `calculator`: "dozwolone operation: add/subtract/multiply/divide";
- `read_file`: "użyj `list_files`, jeśli nie masz pewności czy plik istnieje";
- `verify_task`: "dla tasku `people` pole `answer` musi być listą obiektów z polami name, surname, gender, born, city, tags";
- `download_file`: "podaj pełny URL z `http://` lub `https://`".

To jest dokładnie ten poziom komunikacji, o którym mówi S01E02.

### Etap 7. Zaktualizować testy

Potrzebne zmiany testowe:

- `src/tests/test_runner.py`
  - zamiast oczekiwać plain stringa dla błędu, oczekiwać pełnego JSON payloadu;
- `src/tests/test_tool_registry.py`
  - sprawdzić normalizację nieoczekiwanego exception do kontraktu soft-fail;
- `src/tests/test_wait_tool.py`
  - przestać oczekiwać `ValueError`, oczekiwać `{"ok": false, ...}`;
- `src/tests/test_ai_devs_tools.py`
  - walidacja `people` powinna zwracać soft-fail zamiast exception;
- dodać testy dla tooli plikowych na:
  - path traversal,
  - odczyt katalogu jako pliku,
  - brak pliku,
  - nadpisanie katalogu.

## Minimalny zakres zmian, który daje realny efekt

Jeśli chcesz zrobić to iteracyjnie, to pierwszy wartościowy fix to:

1. zmienić runner tak, aby nie ucinał błędów do stringa;
2. wprowadzić wspólny kontrakt `tool_error(...)`;
3. przepisać `wait`, `calculator`, `files/*`, `verify_task`.

Już ten zakres sprawi, że agent dostanie kontekst pozwalający na korektę kolejnego wywołania.

## Kryteria akceptacji

- żaden przewidywalny błąd walidacyjny toola nie używa `raise`;
- każdy taki błąd wraca do modelu jako JSON z `error`, `hint` i opcjonalnym `details`;
- `handle_turn_response()` zapisuje pełny payload błędu dla wszystkich tooli, nie tylko `verify_task`;
- nieoczekiwany wyjątek nadal jest logowany, ale agent dostaje miękki komunikat systemowy;
- testy pokrywają zarówno poprawne użycie, jak i najważniejsze scenariusze autorecovery.

## Rekomendacja implementacyjna

Nie robiłbym osobnego "globalnego handlera błędów tooli" jako głównego mechanizmu biznesowego.

Lepszy podział odpowiedzialności:

- tool odpowiada za przewidywalne błędy domenowe i walidacyjne;
- registry odpowiada za awarie nieprzewidziane;
- runner odpowiada za zachowanie pełnego payloadu w historii agenta.

To jest najbliższe wzorcowi z S01: narzędzie ma być samoopisujące i ma pomagać agentowi naprawić następną próbę.
