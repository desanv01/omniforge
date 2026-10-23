package defenseeval

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"unicode/utf8"
)

func parseLogs(raw, label string, remaining int) ([]event, error) {
	if !utf8.ValidString(raw) {
		return nil, invalid("%s logs must be correct UTF-8", label)
	}
	out := []event{}
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return out, nil
	}
	if strings.HasPrefix(trimmed, "[") {
		decoder := json.NewDecoder(strings.NewReader(raw))
		decoder.UseNumber()
		if _, err := decoder.Token(); err != nil {
			return nil, invalid("%s Unable to read log array", label)
		}
		for decoder.More() {
			if len(out) >= remaining {
				return nil, invalid("Total log events must be less than 2000")
			}
			start := decoder.InputOffset()
			count := 0
			value, err := readValue(decoder, 0, &count)
			if err != nil {
				return nil, invalid("%[2]dth event in the %[1]s log array: %[3]s", label, len(out)+1, err)
			}
			fields, ok := value.(map[string]any)
			if !ok {
				return nil, invalid("Each event in the %s log must be a JSON object", label)
			}
			if decoder.InputOffset()-start > MaxEventBytes {
				return nil, invalid("An event must be less than 128 KiB")
			}
			out = append(out, event{line: len(out) + 1, fields: fields})
		}
		if close, err := decoder.Token(); err != nil || close != json.Delim(']') {
			return nil, invalid("%s log array is incomplete", label)
		}
		if err := requireEOF(decoder); err != nil {
			return nil, invalid("There are different values ​​behind %s log array", label)
		}
		return out, nil
	}
	for line, text := range strings.Split(raw, "\n") {
		if strings.TrimSpace(text) == "" {
			continue
		}
		if len(out) >= remaining {
			return nil, invalid("Total log events must be less than 2000")
		}
		if len(text) > MaxEventBytes {
			return nil, invalid("%s Log line %d: An event must be less than or equal to 128 KiB", label, line+1)
		}
		fields, err := parseObject(text)
		if err != nil {
			return nil, invalid("%s log line %d: %s", label, line+1, err)
		}
		out = append(out, event{line: line + 1, fields: fields})
	}
	return out, nil
}

func parseObject(raw string) (map[string]any, error) {
	if !utf8.ValidString(raw) {
		return nil, fmt.Errorf("Not valid UTF-8")
	}
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.UseNumber()
	count := 0
	value, err := readValue(decoder, 0, &count)
	if err != nil {
		return nil, err
	}
	object, ok := value.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("I need a JSON object")
	}
	if err := requireEOF(decoder); err != nil {
		return nil, err
	}
	return object, nil
}

func requireEOF(decoder *json.Decoder) error {
	if _, err := decoder.Token(); err != io.EOF {
		return fmt.Errorf("There is additional data behind the JSON value")
	}
	return nil
}

// Token parsing rejects duplicate keys rather than silently letting a later
// field override evidence, and bounds every event before evaluation.
func readValue(decoder *json.Decoder, depth int, count *int) (any, error) {
	if depth > MaxNestingDepth {
		return nil, fmt.Errorf("JSON nesting must be 16 levels or less")
	}
	*count = *count + 1
	if *count > MaxEventValues {
		return nil, fmt.Errorf("Events must have less than or equal to 4096 values")
	}
	token, err := decoder.Token()
	if err != nil {
		return nil, fmt.Errorf("JSON syntax is incorrect")
	}
	switch token := token.(type) {
	case json.Delim:
		switch token {
		case '{':
			object := map[string]any{}
			for decoder.More() {
				keyToken, err := decoder.Token()
				key, ok := keyToken.(string)
				if err != nil || !ok || utf8.RuneCountInString(key) > MaxFieldLength {
					return nil, fmt.Errorf("Object field names must be 128 characters or less")
				}
				if _, exists := object[key]; exists {
					return nil, fmt.Errorf("Duplicate JSON field names are not allowed")
				}
				value, err := readValue(decoder, depth+1, count)
				if err != nil {
					return nil, err
				}
				object[key] = value
			}
			if close, err := decoder.Token(); err != nil || close != json.Delim('}') {
				return nil, fmt.Errorf("JSON object is incomplete")
			}
			return object, nil
		case '[':
			array := []any{}
			for decoder.More() {
				value, err := readValue(decoder, depth+1, count)
				if err != nil {
					return nil, err
				}
				array = append(array, value)
			}
			if close, err := decoder.Token(); err != nil || close != json.Delim(']') {
				return nil, fmt.Errorf("JSON array is not complete")
			}
			return array, nil
		default:
			return nil, fmt.Errorf("JSON value is incorrect")
		}
	case string:
		if len(token) > MaxStringBytes {
			return nil, fmt.Errorf("String value must be less than 64 KiB")
		}
		return token, nil
	case json.Number:
		if len(token) > MaxNumberBytes {
			return nil, fmt.Errorf("Numeric values ​​must be 256 bytes or less")
		}
		return token, nil
	default:
		return token, nil
	}
}
