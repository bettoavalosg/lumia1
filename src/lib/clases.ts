export const clases = (...lista: (string | false | null | undefined)[]): string => lista.filter(Boolean).join(' ')
