.PHONY: test examples schema demo

test:
	python3 -m unittest discover -s tests -v

examples:
	python3 tools/generate_examples.py

schema:
	python3 tools/generate_schema.py

demo:
	python3 -m ail compile examples/hello.ail.json -o build/hello
	./build/hello
