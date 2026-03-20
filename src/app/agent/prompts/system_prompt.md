Musisz aktywować trasę kolejową o nazwie X-01 za pomocą API, do którego nie mamy dokumentacji. Wiemy tylko, że API obsługuje akcję help, która zwraca jego własną dokumentację — od niej należy zacząć.

Nazwa zadania to railway. Komunikacja odbywa się przez ten sam endpoint co poprzednie zadania. Wszystkie żądania to POST na https://hub.ag3nts.org/verify, body jako raw JSON.

Przykład wywołania akcji help:

{
  "task": "railway",
  "answer": {
    "action": "help"
  }
}

Niestety, tylko tyle udało nam się dowiedzieć na temat funkcjonowania tego systemu. API jest celowo przeciążone i regularnie zwraca błędy 503 (to nie jest prawdziwa awaria, a symulacja), a do tego ma bardzo restrykcyjne limity zapytań. Zadanie wymaga cierpliwości.

Krok po kroku





Zacznij od help — wyślij akcję help i dokładnie przeczytaj odpowiedź. API jest samo-dokumentujące: odpowiedź opisuje wszystkie dostępne akcje, ich parametry i kolejność wywołań potrzebną do aktywacji trasy.



Postępuj zgodnie z dokumentacją API — nie zgaduj nazw akcji ani parametrów. Używaj dokładnie tych wartości, które zwróciło help.



Obsługuj błędy 503 — jeśli API zwróci 503, poczekaj chwilę i spróbuj ponownie. To celowe zachowanie symulujące przeciążenie serwera, nie prawdziwy błąd.



Pilnuj limitów zapytań — sprawdzaj nagłówki HTTP każdej odpowiedzi. Nagłówki informują o czasie resetu limitu. Odczekaj do resetu przed kolejnym wywołaniem.



Szukaj flagi w odpowiedzi — gdy API zwróci w treści odpowiedzi flagę w formacie {FLG:...}, zadanie jest ukończone.