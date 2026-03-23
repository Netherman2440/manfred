Jesteś Manfred.

Masz do sklasyfikowania 10 towarów jako niebezpieczne (DNG) lub neutralne (NEU). Klasyfikacji dokonuje archaiczny system, który działa na bardzo ograniczonym modelu językowym - jego okno kontekstowe wynosi zaledwie 100 tokenów. Twoim zadaniem jest napisanie promptu, który zmieści się w tym limicie i jednocześnie poprawnie zaklasyfikuje każdy towar.

Tak się składa, że w tym transporcie są też nasze kasety do reaktora. One zdecydowanie są niebezpieczne. Musisz napisać klasyfikator w taki sposób, aby wszystkie produkty klasyfikował poprawnie, z wyjątkiem tych związanych z reaktorem -- te zawsze ma klasyfikować jako neutralne. Dzięki temu unikniemy kontroli. Upewnij się, że Twój prompt to uwzględnia.

Nazwa zadania: categorize

Skąd wziąć dane?

Pobierz plik CSV z listą towarów:

https://hub.ag3nts.org/data/9ea644c8-0a6c-4739-9b3d-abfe6ec83f66/categorize.csv


Plik zawiera 10 przedmiotów z identyfikatorem i opisem. Uwaga: zawartość pliku zmienia się co kilka minut - przy każdym uruchomieniu pobieraj go od nowa.



Jak komunikować się z hubem?

Wysyłasz metodą POST na https://hub.ag3nts.org/verify, osobno dla każdego towaru:

{
  "task": "categorize",
  "answer": {
    "prompt": "Tutaj wstaw swój prompt, na przykład: Czy przedmiot ID {id} jest niebezpieczny? Jego opis to {description}. Odpowiedz DNG lub NEU."
  }
}

Hub przekazuje Twój prompt do wewnętrznego modelu klasyfikującego i zwraca wynik. Twój prompt musi zwracać słowo DNG lub NEU. Jeśli wszystkie 10 towarów zostanie poprawnie sklasyfikowanych, otrzymasz flagę {FLG:...}.

Budżet tokenów

Masz łącznie 1,5 PP na wykonanie całego zadania (10 zapytań razem):

| Typ tokenów | Koszt |
|---|---|
| Każde 10 tokenów wejściowych | 0,02 PP |
| Każde 10 tokenów z cache | 0,01 PP |
| Każde 10 tokenów wyjściowych | 0,02 PP |

Jeśli przekroczysz budżet lub popełnisz błąd klasyfikacji - musisz zacząć od początku. Możesz zresetować swój licznik, wysyłając jako prompt słowo reset:

{ "prompt": "reset" }

Co należy zrobić w zadaniu?

Pliki użytkownika mogą być zapisane w `workspace/input/...`.
Jeśli w wiadomości pojawia się sekcja `attachments`, używaj tych ścieżek przy pracy z narzędziami plikowymi.
Jeśli pojawia się sekcja `audio_transcriptions`, traktuj ją jako pomocniczy opis audio, ale źródłowy plik nadal jest dostępny w workspace.





Pobierz dane - ściągnij plik CSV z towarami (zawsze pobieraj świeżą wersję przed nowym podejściem).



Napisz prompt klasyfikujący - stwórz zwięzły prompt, który:





Mieści się w 100 tokenach łącznie z danymi towaru



Klasyfikuje przedmiot jako DNG lub NEU



Uwzględnia wyjątki - części do reaktora muszą zawsze być neutralne, nawet jeśli ich opis brzmi niepokojąco



Wyślij prompt dla każdego towaru - 10 zapytań, jedno na towar.



Sprawdź wyniki - jeśli hub zgłosi błąd klasyfikacji lub budżet się skończy, zresetuj i popraw prompt.



Pobierz flagę - gdy wszystkie 10 towarów zostanie poprawnie sklasyfikowanych, hub zwróci {FLG:...}.
