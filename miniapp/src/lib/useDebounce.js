import {
  useEffect,
  useState,
} from 'react';


/**
 * مقدار debounce‌شده — برای ورودی‌هایی مثل جست‌وجو
 * که نباید با هر ضربه کلید درخواست بفرستند.
 *
 * const debounced = useDebouncedValue(value, 350);
 */
export function useDebouncedValue(
  value,
  delay = 350,
) {
  const [
    debounced,
    setDebounced,
  ] = useState(value);


  useEffect(() => {
    const timer = setTimeout(
      () => setDebounced(value),
      delay
    );

    return () =>
      clearTimeout(timer);

  }, [value, delay]);


  return debounced;
}
