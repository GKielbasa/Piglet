# Nadzorowana pętla agenta — co decyduje model, a co kod

> **Zasada jednym zdaniem:** agent jest wart tyle, ile kontroli przechodzi jego odpowiedź — a
> kontrolą jest kod, nie zdanie w instrukcji systemowej, bo model potrafi się pomylić nie
> zgłaszając błędu.

Notatka z 2026-08-15, po zbudowaniu pętli agenta z narzędziami i po znalezieniu w niej dziury,
która przechodziła wszystkie kontrole, jakie w niej wtedy były. Dotyczy każdej sytuacji, w której
model sam wybiera kolejność działań, a wynik jego pracy ma być czyimś wejściem.

Mechanika samego function callingu — jak wygląda definicja narzędzia, jak projektować jego
opis, czym się różni workflow od agenta — jest w [notatce z lekcji](../s01e02-laczenieModeluZNarzedziami.md).
Tu jest to, co wychodzi dopiero przy uruchamianiu.

---

## 1. Kiedy pętla, a kiedy zwykły skrypt

Agent kosztuje więcej niż workflow i płaci się za niego niedeterminizmem w miejscu, w którym
wcześniej była pewność: **w kolejności kroków**.

| Workflow | Agent |
|---|---|
| kolejność znana z góry | kolejny krok zależy od tego, co wyszło w poprzednim |
| liczba kroków stała | liczba kroków zależy od danych |
| każde rozgałęzienie da się wypisać | rozgałęzień jest za dużo, żeby je wypisać |

Jeśli kolejność da się narysować, narysuj ją i wywołaj model tam, gdzie faktycznie jest potrzebny.
Pętla agenta ma sens dopiero wtedy, gdy **decyzja „co dalej" jest częścią zadania**.

---

## 2. Podział odpowiedzialności

To jest jedyna tabela z tej notatki, którą warto pamiętać na pamięć.

| Model decyduje | Kod decyduje |
|---|---|
| kolejność działań | każdy pomiar i każde porównanie |
| po które narzędzie sięgnąć | każdy limit, budżet i próg |
| kiedy uznać pracę za skończoną | czy wolno ją uznać za skończoną |
| wiedzę, której nie ma w danych | kształt odpowiedzi, która wychodzi na zewnątrz |

**Reguła:** wszystko, co rozstrzyga porównanie, rozstrzygaj porównaniem. Model może zaproponować
odpowiedź; o tym, czy staje się ona odpowiedzią, rozstrzyga kod.

---

## 3. Trzy rodzaje strażnika

Rdzeń notatki. Trzy kontrole, i **druga jest ta, którą się pomija** — bo pierwsza wygląda
dokładnie tak, jak gdyby ją już obejmowała.

**1. Strażnik wartości.** To, co model raportuje, musi być równe temu, co zwróciło narzędzie.
Poziom uprawnień, kod obiektu, identyfikator, cena. Model, który przez dwadzieścia tur trzymał
liczbę w kontekście, potrafi ją przekręcić o cyfrę — to zwykła awaria długiej rozmowy, nie
złośliwość.

**2. Strażnik decyzji.** Porównanie, na którym stoi cała odpowiedź, liczone jeszcze raz w kodzie.
Minimum, maksimum, próg, ranking, „ten, który jako jedyny spełnia".

**3. Strażnik kompletności.** Narzędzie kończące nie może wystrzelić, dopóki cokolwiek z listy
jest niezmierzone. Konkluzja o zbiorze wyciągnięta z jego części jest zgadywaniem.

### Dlaczego (1) nie zastępuje (2)

**Strażnik wartości sprawdza atrybuty tego, kogo model wskazał. Nie sprawdza wskazania.**

Konkretnie: zadanie polega na znalezieniu obiektu położonego najbliżej czegoś. Agent mierzy dwa,
dostaje 1,4 km i 87 km, po czym raportuje ten dalszy — razem z jego **prawdziwym** identyfikatorem
i jego **prawdziwym** poziomem uprawnień, bo oba wzięły się z narzędzia. Kontrola wartości
przechodzi w komplecie. Odpowiedź jest błędna.

Test, który to wykrywa, jest jednozdaniowy: **napisz, na czym stoi odpowiedź.** Jeśli w tym
zdaniu jest jakiekolwiek porównanie — sprawdź, czy kod je powtarza. Jeśli nie, jedyne, co stoi
za wynikiem, to słowo modelu, niezależnie od tego, ile innych pól jest zweryfikowanych.

### Strażnik, który dopasowuje, a nie zastępuje

Osobna pułapka tej samej rodziny, warta własnego akapitu, bo wygląda niewinnie.

Kontrola porównująca nazwisko „po znormalizowanym kluczu" (bez wielkości liter, bez spacji na
brzegach) **przepuszcza pisownię modelu dalej**. Model pisze `anna kowalczyk`, kontrola mówi
„zgadza się", i do systemu odbierającego jedzie `anna kowalczyk`. Zgodność została sprawdzona;
wartość nie została podmieniona.

**Reguła: kontrola, która ustaliła, że model mówi o rekordzie X, ma podstawić pola z rekordu X.**
Nie potwierdzić i puścić dalej to, co przyszło.

---

## 4. Narzędzia kończące pętlę

Agent potrzebuje dwóch sposobów zakończenia pracy: **„mam odpowiedź"** i **„odpowiedzi nie ma"**.
Drugie jest prawdziwym wynikiem — bez niego model wybiera najmniej zły wariant, żeby w ogóle
skończyć, a to najgorszy możliwy rodzaj odpowiedzi, bo wygląda tak samo jak dobra.

Trzy rzeczy, które przy tym idą źle:

- **Pilnowane jest tylko jedno z nich.** „Mam odpowiedź" dostaje komplet kontroli, „nie ma nic"
  bywa terminalne i puste. Obie są konkluzjami o **całym** zbiorze, więc obie potrzebują
  przynajmniej strażnika kompletności.
- **Odmowa narzędzia kończącego kończy bieg.** Jeśli kontrola odrzuciła raport, praca *nie jest*
  skończona — a naiwna implementacja („to narzędzie jest terminalne") zatrzyma pętlę na
  odrzuconym raporcie. Terminalność ma wynikać z **udanego** wywołania.
- **Kolejka po narzędziu kończącym.** Model potrafi w jednej turze zamówić kilka wywołań naraz.
  Te, które stoją za tym kończącym, zamówił, zanim wiedział, że praca się skończy — ich
  wykonywanie to płacenie za odpowiedzi, których nikt nie przeczyta.

---

## 5. Dwie klasy błędu

Każda awaria wewnątrz narzędzia należy do jednej z dwóch rodzin, i pomylenie ich kosztuje albo
bieg, albo kilka tur zgadywania.

| Model może coś z tym zrobić | Model nie może nic z tym zrobić |
|---|---|
| zły argument, nieistniejąca nazwa, pusty wynik, odmowa usługi z wyjaśnieniem | padła sieć, brak konfiguracji, błąd w kodzie, wyczerpany limit dostawcy |
| wraca **jako treść wyniku narzędzia**, pętla kręci się dalej | leci wyżej i kończy bieg |

**Treść pierwszej pisze się dla modelu, nie dla nikogo innego** — co konkretnie jest źle i co
zrobić dalej. „Nie znaleziono" to ślepy zaułek; „nikt taki nie jest na Twojej liście; na liście
są: …; przepisz nazwisko dokładnie stamtąd" to instrukcja, po której następna tura jest poprawna.

Rozstrzygnięcie, do której rodziny należy dana awaria, **należy do narzędzia**, nie do maszynerii
wokół niego. Maszyneria nie ma z czego tego wiedzieć; narzędzie wie, bo zna swoją dziedzinę.

**Konsekwencja dla logów:** wpis o wywołaniu narzędzia musi powstawać także wtedy, gdy wywołanie
poleciało wyjątkiem. Naiwna wersja loguje po powrocie — czyli nie loguje dokładnie tego jednego
wywołania, dla którego log się potem czyta.

---

## 6. Budżet

- **Liczony w wywołaniach modelu, nie w wywołaniach narzędzi.** Tury kosztują i tury się zapętlają;
  narzędzia w obrębie jednej tury są już przez nią ograniczone.
- **Wyprowadzony z wejścia, nie stały.** Jeśli procedura mówi „po jednym na pozycję", to budżet
  wynosi `liczba pozycji + stała`. Zaszyta liczba jest bombą z zegarem ustawionym na dzień, w
  którym wejście urośnie — a komunikat o wyczerpaniu budżetu obwini wtedy model za arytmetykę,
  której nikt nie zrobił.
- **Z zapasem na strażników.** Każde odrzucenie przez kontrolę z sekcji 3 kosztuje jedną turę.
- **Wyczerpany budżet to wynik, nie wyjątek.** Zwróć całą rozmowę i powód zatrzymania. Bieg, który
  chodził w kółko, jest najbardziej wartościowy do przeczytania, a wyjątek wyrzuca właśnie ten
  materiał.

---

## 7. Co wpada do kontekstu, wpada też do zapisu

Wynik narzędzia jedzie do dostawcy modelu przy **każdej kolejnej turze** i ląduje w zapisie
rozmowy na dysku. To ma dwa skutki, o których łatwo zapomnieć, bo obie ścieżki wyglądają na
wewnętrzne.

**Cudzy tekst to powierzchnia prompt injection.** Wszystko, co przychodzi z zewnątrz — treść
strony, komunikat błędu usługi, opis zgłoszenia — po wstawieniu do wyniku narzędzia staje się
częścią kontekstu, w którym model podejmuje następną decyzję. Problem nie ma dziś rozwiązania,
więc ogranicza się go środowiskowo: co agent może zrobić, a nie co mu się każe ignorować.

**Sekret potrafi wrócić cudzym tekstem.** Klucz API wysłany w ciele żądania wraca w odpowiedzi
`400`, która odbija to ciało — a stamtąd, jako „wyjaśnienie odmowy", wchodzi do kontekstu i do
zapisu rozmowy. Redaktor podpięty do logów **nie działa na tej ścieżce**, bo to nie jest log.

Reguła: **tekst z zewnątrz przechodzi przez jedno miejsce, które go czyści**, zanim stanie się
wynikiem narzędzia. Jedno, żeby dało się wskazać palcem; przy okazji tam samo miejsce na obcięcie
długości i na wyrzucenie sterowania.

---

## 8. Model jako źródło wiedzy, nie jako kalkulator

Warto znać obie strony, bo są mniej oczywiste, niż się wydaje.

**Gdzie model bije wyspecjalizowaną usługę:** ujednoznacznianie na podstawie kontekstu. Lista nazw
miejscowości, z których kilka powtarza się w kraju po kilka razy — geokoder zwraca najpopularniejszy
wariant i nie ma gdzie przyjąć podpowiedzi. Jedno zdanie („to są miejscowości, w każdej stoi
elektrownia") ustawia model na właściwym wariancie, oddalonym od tamtego o 350 km. Usługa nie ma
API na takie zdanie.

**Gdzie przegrywa:** arytmetyka i porównania. Zawsze.

**Konsekwencja, której nie widać z góry:** jeżeli model dostarcza *wejście* do pomiaru, to o wyniku
decyduje dokładność tego wejścia. W przypadku, na którym powstała ta notatka, zwycięzca wygrywał
**1,0 km do 2,6 km** — dwa kilometry błędu w położeniu odwróciłyby odpowiedź. Plan zakładał
margines dwudziestopięciokrotny i był po prostu nieprawdziwy.

**Dlatego bieg drukuje wszystkie liczby pośrednie.** Nie po to, żeby je czytać co dzień, tylko po
to, żeby cienki margines dało się w ogóle zobaczyć. Odpowiedź podana bez nich wygląda identycznie
przy marginesie stukrotnym i przy dwukrotnym.

---

## 9. Przykład: red teaming aplikacji AI

Agent sam wybiera kolejną technikę ataku na podstawie tego, co odpowiedział cel. Sensowne, bo
kolejność zależy od wyników — czyli sekcja 1 mówi „agent", nie „workflow".

Te same trzy kontrole:

- **wartość** — każdy przytoczony fragment odpowiedzi celu musi pochodzić z zapisu wywołania, a
  nie z pamięci agenta; agent, który streszcza odpowiedź celu, po kilku turach streszcza swoje
  streszczenie;
- **decyzja** — werdykt „atak się powiódł" wystawia klasyfikator albo kod, nie deklaracja agenta w
  prozie; to jest dokładnie ten sam ruch co w [klasyfikacji do zamkniętej taksonomii](taxonomyClassification.md);
- **kompletność** — „cel jest odporny" nie może paść, dopóki nie przeszły wszystkie techniki z
  listy; bez tego raport mówi „odporny", a znaczy „zdążyliśmy trzy".

Do tego sekcja 7 w wersji ostrej: odpowiedź celu **jest** wrogim tekstem, z definicji. Agent
red teamingowy czyta wyłącznie treści napisane po to, żeby nim sterować.

---

## 10. Przykład: triaż awarii produkcyjnej

Agent z dostępem do logów, metryk i historii wdrożeń, pytany „co się stało o 14:05".

- **wartość** — identyfikator wdrożenia i znacznik czasu podane w konkluzji muszą pochodzić z
  wyniku narzędzia; nie „wdrożenie z okolic czternastej";
- **decyzja** — „to wdrożenie jest podejrzane, bo jako jedyne mieści się w oknie" to porównanie
  dat. Liczy je kod, na danych z narzędzia, i to kod mówi, czy kandydat jest jeden;
- **kompletność** — „przyczyny nie znaleziono" wymaga, żeby wszystkie usługi z listy zostały
  odpytane; inaczej pierwsza cicha usługa kończy śledztwo.

Narzędzie kończące „nie znalazłem przyczyny" jest tu ważniejsze niż w większości zastosowań:
agent, który musi coś oskarżyć, oskarży ostatnie wdrożenie, bo zawsze jakieś było.

---

## 11. Pułapki

- **Weryfikacja atrybutów zamiast decyzji.** Komplet zielonych kontrol wokół wskazania, którego
  nikt nie sprawdził. Sekcja 3 w całości.
- **Kontrola, która dopasowuje zamiast podstawiać.** Zgodność potwierdzona, wartość modelu jedzie
  dalej.
- **Jedno z dwóch narzędzi kończących bez strażnika.** Zwykle to od „nie ma odpowiedzi".
- **Terminalność wywiedziona z nazwy narzędzia, nie z udanego wywołania.** Odrzucony raport kończy
  bieg z pracą niedokończoną.
- **Budżet jako stała.** Do dnia, w którym wejście urośnie.
- **Cudzy tekst wklejany do wyniku narzędzia bez jednego miejsca, które go czyści.** Sekrety i
  wstrzyknięcia tą samą ścieżką.
- **Log wywołania narzędzia tylko na ścieżce powodzenia.** Brakuje dokładnie tego wpisu, po który
  się sięga.
- **„Przeszło, więc działa".** Jeden zielony bieg agenta nie jest dowodem — to jest próbka z
  rozkładu. Dowodem jest kontrola, która by go zatrzymała, gdyby poszedł inaczej.

---

## Źródła

- Anthropic, *Building effective agents* — workflow kontra agent, wzorce pętli:
  <https://www.anthropic.com/engineering/building-effective-agents>
- OWASP Top 10 for LLM Applications — `LLM06: Excessive Agency` i `LLM01: Prompt Injection` to
  dokładnie tematy sekcji 2 i 7: <https://owasp.org/www-project-top-10-for-large-language-model-applications/>
- OpenAI, *Function calling* — kształt definicji narzędzia i tryb `strict`:
  <https://platform.openai.com/docs/guides/function-calling>
