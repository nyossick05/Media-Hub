public class Mammal extends Animal
{
    private boolean domesticated;   
    private boolean ismarine;
    public Mammal(String name, int population, boolean ismarine, boolean domesticated) 
    {
        super(name, "Mammal", population);
        this.ismarine = ismarine;
        this.domesticated = domesticated;
    }
}
