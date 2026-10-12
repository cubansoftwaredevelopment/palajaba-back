# Tests e2e

Desde `palajaba-back`, con MongoDB en marcha (`mongodb://localhost:27017` o la URL de `MONGODB_URL`).

## Todos

```powershell
.\venv\Scripts\python.exe -m unittest discover -s test_e2e -t . -v
```

## Uno

Un módulo:

```powershell
.\venv\Scripts\python.exe -m unittest test_e2e.product_search.test_product_search_e2e -v
```

Un solo test, con la clase y el método:

```powershell
.\venv\Scripts\python.exe -m unittest test_e2e.product_search.test_product_search_e2e.ProductSearchE2ETests.test_blank_query_lists_only_ordered_available_products -v
```

## Más de uno

Lista los módulos separados por espacio:

```powershell
.\venv\Scripts\python.exe -m unittest test_e2e.product_search.test_product_search_e2e test_e2e.product_popularity.test_product_popularity_e2e test_e2e.categories.test_categories_e2e test_e2e.statistics.test_statistics_e2e -v
```

Igual con tests sueltos: repite la ruta `módulo.Clase.método` por cada uno.
