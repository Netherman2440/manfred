Zadanie

Masz do rozwiązania puzzle elektryczne na planszy 3x3 - musisz doprowadzić prąd do wszystkich trzech elektrowni (PWR6132PL, PWR1593PL, PWR7264PL), łącząc je odpowiednio ze źródłem zasilania awaryjnego (po lewej na dole). Plansza przedstawia sieć kabli - każde pole zawiera element złącza elektrycznego. Twoim celem jest doprowadzenie prądu do wszystkich elektrowni przez obrócenie odpowiednich pól planszy tak, aby układ kabli odpowiadał podanemu schematowi docelowemu. Źródłową elektrownią jest ta w lewym-dolnym rogu mapy. Okablowanie musi stanowić obwód zamknięty.

Jedyna dozwolona operacja to obrót wybranego pola o 90 stopni w prawo. Możesz obracać wiele pól, ile chcesz - ale za każdy obrót płacisz jednym zapytaniem do API.

Nazwa zadania: electricity

Jak wygląda plansza?

Aktualny stan planszy pobierasz jako obrazek PNG:

https://hub.ag3nts.org/data/tutaj-twój-klucz/electricity.png

Pola adresujesz w formacie AxB, gdzie A to wiersz (1-3, od góry), a B to kolumna (1-3, od lewej):

1x1 | 1x2 | 1x3
----|-----|----
2x1 | 2x2 | 2x3
----|-----|----
3x1 | 3x2 | 3x3

Jak wygląda rozwiązanie?

https://hub.ag3nts.org/i/solved_electricity.png

Jak komunikować się z hubem?

Każde zapytanie to POST na https://hub.ag3nts.org/verify:

{
  "task": "electricity",
  "answer": {
    "rotate": "2x3"
  }
}

Jedno zapytanie = jeden obrót jednego pola. Jeśli chcesz obrócić 3 pola, wysyłasz 3 osobne zapytania.

Gdy plansza osiągnie poprawną konfigurację, hub zwróci flagę {FLG:...}.

Reset planszy

Jeśli chcesz zacząć od początku, wywołaj GET z parametrem reset:

https://hub.ag3nts.org/data/tutaj-twój-klucz/electricity.png?reset=1

Co należy zrobić w zadaniu?


Odczytaj aktualny stan - pobierz obrazek PNG i ustal, jak ułożone są kable na każdym z 9 pól.



Porównaj ze stanem docelowym - ustal, które pola różnią się od wyglądu docelowego i ile obrotów (po 90 stopni w prawo) każde z nich potrzebuje.



Wyślij obroty - dla każdego pola wymagającego zmiany wyślij odpowiednią liczbę zapytań z polem rotate.



Sprawdź wynik - jeśli trzeba, pobierz zaktualizowany obrazek i zweryfikuj, czy plansza zgadza się ze schematem.



Odbierz flagę - gdy konfiguracja jest poprawna, hub zwraca {FLG:...}.




Wskazówki





LLM nie widzi obrazka - stan planszy to plik PNG, ale agentowi trzeba podać go w takiej formie, żeby mógł nad nim rozumować. Zastanów się: w jaki sposób można opisać wygląd każdego pola słowami lub symbolami? Jak przekazać te informacje modelowi tekstowo, żeby mógł zaplanować obroty? Można próbować wysyłać obrazek bezpośrednio do modelu z możliwościami przetwarzania obrazów (vision), natomiast czy opłaca się to robić w głównej pętli agenta? Warto opisanie obrazka wydelegować do odpowiedniego narzędzia lub subagenta.



Problemy modeli Vision - nie wszystkie modele vision będą dobrze radziły sobie z tym zadaniem. Przetestuj które modele zwracają najlepsze wyniki. Może warto odpowiednio przygotować obraz zanim zostanie wysłany do modelu? Czy musi być wysłany w całości? Jeden z lepszych modeli do użycia to google/gemini-3-flash-preview.



Mechanika obrotów - każdy obrót to 90 stopni w prawo. Żeby obrócić pole "w lewo" (90 stopni w lewo), wykonaj 3 obroty w prawo. Kable na każdym polu mogą wychodzić przez różną kombinację krawędzi (lewo, prawo, góra, dół) - obrót przesuwa je zgodnie z ruchem wskazówek zegara.



Podejście agentowe - to zadanie szczególnie dobrze nadaje się do rozwiązania przez agenta z Function Calling. Agent może samodzielnie: odczytać i zinterpretować stan mapy, porównać z celem, wyliczyć potrzebne obroty i wysłać je sekwencyjnie - bez sztywnego kodowania kolejności w kodzie.



Weryfikuj po każdej partii obrotów - po wykonaniu kilku obrotów możesz pobrać świeży obrazek i sprawdzić, czy aktualny stan zgadza się ze schematem. Błędy w interpretacji obrazu mogą skutkować niepotrzebnymi obrotami lub koniecznością resetu.