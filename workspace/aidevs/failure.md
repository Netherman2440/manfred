Wczoraj w elektrowni doszło do awarii. Masz dostęp do pełnego pliku logów systemowych z tego dnia - ale jest on ogromny. Twoje zadanie to przygotowanie skondensowanej wersji logów, która:

zawiera wyłącznie zdarzenia istotne dla analizy awarii (zasilanie, chłodzenie, pompy wodne, oprogramowanie i inne podzespoły elektrowni),

mieści się w 1500 tokenach,

zachowuje format wieloliniowy - jedno zdarzenie na linię.


Skondensowane logi wysyłasz do Centrali. Technicy weryfikują, czy na ich podstawie można przeprowadzić analizę przyczyny awarii. Jeśli tak - otrzymujesz flagę.

Nazwa zadania: failure

Skąd wziąć dane?

Pobierz pełny plik logów:

https://hub.ag3nts.org/data/tutaj-twój-klucz/failure.log

CZYTANIE CAŁEGO  failure.log to RACZEJ KIEPSKI POMYSŁ
czytaj raczej fragmentami lub szukaj konrketnej frazy

Jak wysłać odpowiedź?

Metodą POST na https://hub.ag3nts.org/verify:

{
  "task": "failure",
  "answer": {
    "logs": "[2026-02-26 06:04] [CRIT] ECCS8 runaway outlet temp. Protection interlock initiated reactor trip.\n[2026-02-26 06:11] [WARN] PWR01 input ripple crossed warning limits.\n[2026-02-26 10:15] [CRIT] WTANK07 coolant below critical threshold. Hard trip initiated."
  }
}

Pole logs to string - wiersze oddzielone znakiem \n. Każdy wiersz to jedno zdarzenie.

Wymagania formatowe

Jeden wiersz = jedno zdarzenie - nie łącz wielu zdarzeń w jednej linii

Data w formacie YYYY-MM-DD - technicy muszą wiedzieć, którego dnia zdarzenie miało miejsce

Godzina w formacie HH:MM lub H:MM - żeby umieścić zdarzenie w czasie

Możesz skracać i parafrazować - ważne żeby zachować: znacznik czasu, poziom ważności i identyfikator podzespołu

Nie przekraczaj 1500 tokenów - to twarde ograniczenie systemu Centrali. Możesz sprawdzić liczbę tokenów na https://platform.openai.com/tokenizer

Co należy zrobić w zadaniu?





Pobierz plik logów - sprawdź jego rozmiar. Ile ma linii? Ile tokenów zajmuje cały plik?



Wyfiltruj istotne zdarzenia - z tysięcy wpisów wybierz tylko te dotyczące podzespołów elektrowni i awarii. Jak można stwierdzić które zdarzenia istotnie przyczyniły się do awarii? Które są najważniejsze?



Skompresuj do limitu - upewnij się, że wynikowy plik mieści się w 1500 tokenach. Możesz skracać opisy zdarzeń, byleby zachować kluczowe informacje.



Wyślij i przeczytaj odpowiedź - Centrala zwraca szczegółową informację zwrotną od techników: czego brakuje, które podzespoły są niejasne lub niewystarczająco opisane. Wykorzystaj tę informację do poprawienia logów.



Popraw i wyślij ponownie - iteruj na podstawie feedbacku, aż technicy potwierdzą kompletność i otrzymasz flagę {FLG:...}.