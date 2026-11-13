package {{JAVA_PACKAGE}};

public final class App {
    private App() {}

    public static String greeting() {
        return "{{PROJECT_NAME}}";
    }

    public static void main(String[] args) {
        System.out.println(greeting());
    }
}
